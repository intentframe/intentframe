"""Hybrid RAG indexer: SQLite FTS5 + sqlite-vec.

Maintains a SQLite database at ~/.jarvis/index/memory.db with:
  - files table       – tracks file hashes for incremental re-indexing
  - chunks table      – line-aware text chunks with embeddings
  - chunks_fts        – FTS5 virtual table for BM25 keyword search
  - chunks_vec        – sqlite-vec virtual table for vector similarity

Uses chonkie for smart text chunking, xxhash for fast file change
detection, and the OpenAI embeddings API for dense vectors.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
import time
from pathlib import Path
from typing import Any

import xxhash
from chonkie import RecursiveChunker
from loguru import logger
from openai import AsyncOpenAI

from jarvis.config import JarvisConfig

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    hash TEXT NOT NULL,
    mtime INTEGER NOT NULL,
    size  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id         TEXT PRIMARY KEY,
    path       TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line   INTEGER NOT NULL,
    hash       TEXT NOT NULL,
    text       TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    id UNINDEXED,
    path UNINDEXED,
    start_line UNINDEXED,
    end_line UNINDEXED
);

CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);
"""

VEC_TABLE_SQL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[{dims}]
);
"""


class MemoryIndexer:
    """Indexes workspace markdown files into SQLite for hybrid search."""

    def __init__(self, db_path: Path, config: JarvisConfig) -> None:
        self.db_path = db_path
        self.config = config
        self.db: sqlite3.Connection | None = None
        self._openai = AsyncOpenAI()
        self._chunker: RecursiveChunker | None = None

    # -- lifecycle -----------------------------------------------------------

    def open(self) -> None:
        """Open the database connection and ensure schema exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.db_path))
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.row_factory = sqlite3.Row

        # Load sqlite-vec extension.
        try:
            import sqlite_vec
            self.db.enable_load_extension(True)
            sqlite_vec.load(self.db)
            self.db.enable_load_extension(False)
            logger.debug("sqlite-vec extension loaded")
        except Exception as exc:
            logger.warning(f"sqlite-vec not available — vector search disabled: {exc}")

        self._ensure_schema()

        # Initialize chonkie chunker.
        self._chunker = RecursiveChunker(
            chunk_size=self.config.chunk_size_tokens,
        )
        logger.debug(f"MemoryIndexer opened: {self.db_path}")

    def close(self) -> None:
        """Close the database connection."""
        if self.db is not None:
            self.db.close()
            self.db = None

    def _ensure_schema(self) -> None:
        """Create tables if they don't exist."""
        assert self.db is not None
        self.db.executescript(SCHEMA_SQL)
        try:
            self.db.executescript(
                VEC_TABLE_SQL.format(dims=self.config.embedding_dims)
            )
        except sqlite3.OperationalError:
            # sqlite-vec not loaded; vector table creation will fail silently.
            pass
        self.db.commit()

    # -- indexing -------------------------------------------------------------

    async def index_workspace(self, workspace_dir: Path, actor: Any = None) -> None:
        """Re-index all markdown files in the workspace. Skip unchanged files."""
        if self.db is None:
            self.open()

        md_files = list(workspace_dir.rglob("*.md"))
        indexed = 0
        skipped = 0

        for md_path in md_files:
            stat = md_path.stat()
            current_hash = self._hash_file(md_path)
            stored = self._get_file(str(md_path))

            if stored and stored["hash"] == current_hash:
                skipped += 1
                continue

            # File changed or is new — re-index it.
            content = md_path.read_text(encoding="utf-8", errors="replace")
            chunks = self._chunk_text(content, md_path)

            if not chunks:
                continue

            texts = [c["text"] for c in chunks]
            embeddings = await self._embed_chunks(texts)
            self._upsert_chunks(md_path, current_hash, chunks, embeddings)

            # Update file record.
            assert self.db is not None
            self.db.execute(
                "INSERT OR REPLACE INTO files (path, hash, mtime, size) VALUES (?, ?, ?, ?)",
                (str(md_path), current_hash, int(stat.st_mtime), stat.st_size),
            )
            self.db.commit()
            indexed += 1

        logger.info(f"Index workspace: {indexed} files indexed, {skipped} unchanged")

    def _get_file(self, path: str) -> dict[str, Any] | None:
        """Return the stored file metadata, or None."""
        assert self.db is not None
        row = self.db.execute(
            "SELECT path, hash, mtime, size FROM files WHERE path = ?", (path,)
        ).fetchone()
        return dict(row) if row else None

    def _chunk_text(self, content: str, path: Path) -> list[dict[str, Any]]:
        """Chunk text using chonkie RecursiveChunker, preserving line numbers."""
        if self._chunker is None:
            return []

        try:
            chonkie_chunks = self._chunker.chunk(content)
        except Exception as exc:
            logger.warning(f"Chonkie chunking failed for {path.name}: {exc}")
            return []

        lines = content.splitlines()
        # Build a character-offset → line-number map for efficient lookup.
        line_starts: list[int] = []
        offset = 0
        for line in lines:
            line_starts.append(offset)
            offset += len(line) + 1  # +1 for newline

        def char_to_line(char_offset: int) -> int:
            lo, hi = 0, len(line_starts) - 1
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if line_starts[mid] <= char_offset:
                    lo = mid
                else:
                    hi = mid - 1
            return lo + 1  # 1-indexed

        result = []
        for i, chunk in enumerate(chonkie_chunks):
            text = chunk.text if hasattr(chunk, "text") else str(chunk)
            start_char = getattr(chunk, "start_index", None)
            end_char = getattr(chunk, "end_index", None)

            if start_char is not None and end_char is not None:
                start_line = char_to_line(start_char)
                end_line = char_to_line(end_char)
            else:
                start_line = 1
                end_line = len(lines)

            chunk_hash = xxhash.xxh3_64(text.encode()).hexdigest()
            chunk_id = f"{path}:{start_line}-{end_line}"

            result.append({
                "id": chunk_id,
                "path": str(path),
                "start_line": start_line,
                "end_line": end_line,
                "hash": chunk_hash,
                "text": text,
            })

        return result

    async def _embed_chunks(self, texts: list[str]) -> list[list[float]]:
        """Call OpenAI embeddings API for a batch of texts."""
        if not texts:
            return []

        embeddings: list[list[float]] = []
        batch_size = 2048

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            try:
                response = await self._openai.embeddings.create(
                    model=self.config.embedding_model,
                    input=batch,
                    dimensions=self.config.embedding_dims,
                )
                for item in response.data:
                    embeddings.append(item.embedding)
            except Exception as exc:
                logger.warning(f"Embedding batch {i//batch_size} failed: {exc}")
                # Append zero vectors so chunk count stays aligned.
                embeddings.extend([[0.0] * self.config.embedding_dims] * len(batch))

        return embeddings

    def _upsert_chunks(
        self,
        path: Path,
        file_hash: str,
        chunks: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        """Insert or update chunks + embeddings in all three tables."""
        if self.db is None:
            return

        now = int(time.time())
        path_str = str(path)

        # Remove stale chunks for this file.
        # Delete from chunks_vec first — its subquery reads the chunks table.
        try:
            self.db.execute("DELETE FROM chunks_vec WHERE id IN (SELECT id FROM chunks WHERE path = ?)", (path_str,))
        except sqlite3.OperationalError:
            pass  # chunks_vec may not exist if sqlite-vec is unavailable
        self.db.execute("DELETE FROM chunks_fts WHERE path = ?", (path_str,))
        self.db.execute("DELETE FROM chunks WHERE path = ?", (path_str,))

        for chunk, embedding in zip(chunks, embeddings):
            cid = chunk["id"]

            # Main chunks table.
            self.db.execute(
                "INSERT OR REPLACE INTO chunks (id, path, start_line, end_line, hash, text, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid, path_str, chunk["start_line"], chunk["end_line"], chunk["hash"], chunk["text"], now),
            )

            # FTS5 virtual table.
            self.db.execute(
                "INSERT INTO chunks_fts (text, id, path, start_line, end_line) VALUES (?, ?, ?, ?, ?)",
                (chunk["text"], cid, path_str, chunk["start_line"], chunk["end_line"]),
            )

            # Vector table (sqlite-vec binary format).
            try:
                vec_blob = struct.pack(f"{len(embedding)}f", *embedding)
                self.db.execute(
                    "INSERT OR REPLACE INTO chunks_vec (id, embedding) VALUES (?, ?)",
                    (cid, vec_blob),
                )
            except sqlite3.OperationalError:
                pass  # sqlite-vec unavailable

        self.db.commit()
        logger.debug(f"Upserted {len(chunks)} chunks for {path.name}")

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _hash_file(path: Path) -> str:
        """Fast file hash using xxhash."""
        hasher = xxhash.xxh3_64()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
