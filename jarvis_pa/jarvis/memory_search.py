"""Hybrid memory search: BM25 (FTS5) + vector similarity (sqlite-vec).

Combines keyword search and semantic search with weighted score merging.
Both search modes hit the same SQLite database as the indexer, so no
extra process or network hop is needed.
"""

from __future__ import annotations

import struct
import sqlite3
from pathlib import Path
from typing import Any

from loguru import logger
from openai import AsyncOpenAI

from jarvis.config import JarvisConfig
from jarvis.types import SearchResult


class MemorySearcher:
    """Hybrid BM25 + vector searcher over the SQLite memory index."""

    def __init__(self, db_path: Path, config: JarvisConfig) -> None:
        self.db_path = db_path
        self.config = config
        self.db: sqlite3.Connection | None = None
        self._openai = AsyncOpenAI()
        self._vec_available = False

    # -- lifecycle -----------------------------------------------------------

    def open(self) -> None:
        """Open the database connection."""
        if not self.db_path.exists():
            logger.debug("Memory index does not exist yet — search will return empty")
            return
        self.db = sqlite3.connect(str(self.db_path))
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.row_factory = sqlite3.Row
        try:
            import sqlite_vec
            self.db.enable_load_extension(True)
            sqlite_vec.load(self.db)
            self.db.enable_load_extension(False)
            self._vec_available = True
            logger.debug("MemorySearcher: sqlite-vec loaded")
        except Exception as exc:
            logger.warning(f"sqlite-vec unavailable — text search only: {exc}")

    def close(self) -> None:
        """Close the database connection."""
        if self.db is not None:
            self.db.close()
            self.db = None

    # -- public API ----------------------------------------------------------

    async def search(self, query: str) -> list[SearchResult]:
        """Hybrid BM25 + vector search. Returns ranked list of SearchResult."""
        if self.db is None:
            self.open()
        if self.db is None:
            return []

        candidates = self.config.search_max_results * self.config.search_candidate_multiplier

        # 1. FTS keyword search.
        fts_results = self._fts_search(query, candidates)

        # 2. Vector search (if available).
        vec_results: dict[str, float] = {}
        if self._vec_available:
            try:
                embedding = await self._embed_query(query)
                vec_results = self._vector_search(embedding, candidates)
            except Exception as exc:
                logger.warning(f"Vector search failed, falling back to FTS only: {exc}")

        # 3. Merge scores.
        merged = self._hybrid_merge(fts_results, vec_results)

        # 4. Hydrate chunks and return.
        results: list[SearchResult] = []
        for chunk_id, score in merged:
            if score < self.config.search_min_score:
                continue
            chunk = self._get_chunk(chunk_id)
            if chunk is None:
                continue
            results.append(SearchResult(
                chunk_id=chunk_id,
                path=chunk["path"],
                start_line=chunk["start_line"],
                end_line=chunk["end_line"],
                text=chunk["text"],
                score=score,
            ))
            if len(results) >= self.config.search_max_results:
                break

        logger.debug(f"search({query!r:.40}) → {len(results)} results")
        return results

    # -- internals -----------------------------------------------------------

    def _fts_search(self, query: str, limit: int) -> dict[str, float]:
        """BM25 keyword search via FTS5. Returns {chunk_id: normalised_score}."""
        assert self.db is not None
        # FTS5 rank is negative; closer to 0 is better.
        try:
            rows = self.db.execute(
                "SELECT id, rank FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                (query, limit),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            # Query syntax error (e.g. special chars) — fall back gracefully.
            logger.debug(f"FTS query failed ({exc}) — trying plain LIKE fallback")
            try:
                rows = self.db.execute(
                    "SELECT id, rank FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                    (f'"{query}"', limit),
                ).fetchall()
            except sqlite3.OperationalError:
                return {}

        return {row["id"]: self._bm25_rank_to_score(row["rank"]) for row in rows}

    def _vector_search(self, embedding: list[float], limit: int) -> dict[str, float]:
        """Cosine similarity search via sqlite-vec. Returns {chunk_id: score}."""
        assert self.db is not None
        vec_blob = struct.pack(f"{len(embedding)}f", *embedding)
        rows = self.db.execute(
            "SELECT id, distance FROM chunks_vec WHERE embedding MATCH ? AND k = ?",
            (vec_blob, limit),
        ).fetchall()
        # Distance is L2; convert to similarity score.
        return {row["id"]: self._distance_to_score(row["distance"]) for row in rows}

    def _hybrid_merge(
        self,
        fts: dict[str, float],
        vec: dict[str, float],
    ) -> list[tuple[str, float]]:
        """Merge FTS and vector scores with configured weights, sorted descending."""
        all_ids = set(fts.keys()) | set(vec.keys())
        vw = self.config.hybrid_vector_weight
        tw = self.config.hybrid_text_weight

        scored: list[tuple[str, float]] = []
        for cid in all_ids:
            fts_score = fts.get(cid, 0.0)
            vec_score = vec.get(cid, 0.0)
            if vec and not fts:
                # Vector-only fallback
                final = vec_score
            elif fts and not vec:
                # Text-only fallback
                final = fts_score
            else:
                final = vw * vec_score + tw * fts_score
            scored.append((cid, final))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    async def _embed_query(self, query: str) -> list[float]:
        """Embed a single query string."""
        response = await self._openai.embeddings.create(
            model=self.config.embedding_model,
            input=[query],
            dimensions=self.config.embedding_dims,
        )
        return response.data[0].embedding

    def _get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        """Fetch chunk metadata from the chunks table."""
        assert self.db is not None
        row = self.db.execute(
            "SELECT id, path, start_line, end_line, text FROM chunks WHERE id = ?",
            (chunk_id,),
        ).fetchone()
        return dict(row) if row else None

    # -- static helpers ------------------------------------------------------

    @staticmethod
    def _bm25_rank_to_score(rank: float) -> float:
        """Convert FTS5 rank (negative, closer-to-0 = better) to [0,1] score."""
        return 1.0 / (1.0 + abs(rank))

    @staticmethod
    def _distance_to_score(distance: float) -> float:
        """Convert L2 distance (lower = better) to [0,1] similarity score."""
        return 1.0 / (1.0 + distance)
