"""All configuration. Every tunable value lives here.

Uses pydantic-settings so that:
  - Defaults are defined once in the class.
  - ~/.jarvis/config.yaml overlays any field by name.
  - JARVIS_* environment variables override everything.
  - No manual _apply_yaml / _apply_env code needed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


class _YamlConfigSource(PydanticBaseSettingsSource):
    """Load settings from ~/.jarvis/config.yaml (or a custom path)."""

    def __init__(self, settings_cls: type[BaseSettings], yaml_path: Path | None = None) -> None:
        super().__init__(settings_cls)
        self._yaml_path = yaml_path or Path("~/.jarvis/config.yaml").expanduser()

    def get_field_value(self, field: Any, field_name: str) -> Any:  # type: ignore[override]
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        if not self._yaml_path.exists():
            return {}
        try:
            raw = yaml.safe_load(self._yaml_path.read_text()) or {}
            return {k: v for k, v in raw.items() if v is not None}
        except Exception:
            return {}


class JarvisConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JARVIS_",
        env_ignore_empty=True,
        extra="ignore",
    )

    # Paths
    workspace_dir: Path = Path("~/.jarvis")
    socket_path: str = "~/.intentframe/run/intentframe.sock"

    # Identity
    agent_id: str = "jarvis"
    user_id: str = "jarvis_default"

    # LLM
    model: str = "gpt-5-mini-2025-08-07"
    sub_agent_model: str = "gpt-5-mini-2025-08-07"

    # Context window
    context_window_tokens: int = 128_000
    max_history_share: float = 0.5
    compaction_threshold: float = 0.8

    # Memory index (hybrid RAG)
    chunk_size_tokens: int = 400
    chunk_overlap_tokens: int = 80
    embedding_model: str = "text-embedding-3-small"
    embedding_dims: int = 1536
    hybrid_vector_weight: float = 0.7
    hybrid_text_weight: float = 0.3
    search_max_results: int = 6
    search_min_score: float = 0.35
    search_candidate_multiplier: int = 4

    # Auto-capture
    auto_capture_min_len: int = 10
    auto_capture_max_len: int = 500

    # Heartbeat
    heartbeat_enabled: bool = True
    heartbeat_interval_minutes: int = 30
    heartbeat_active_hours_start: str = "08:00"
    heartbeat_active_hours_end: str = "22:00"
    heartbeat_ack_max_chars: int = 50

    # Server
    chat_timeout_seconds: int = 600

    # Session
    session_idle_expire_minutes: int = 60

    # Skills – populated post-init
    skill_dirs: list[Path] = []

    @field_validator("workspace_dir", mode="before")
    @classmethod
    def _expand_workspace(cls, v: Any) -> Path:
        return Path(v).expanduser()

    @field_validator("skill_dirs", mode="before")
    @classmethod
    def _expand_skill_dirs(cls, v: Any) -> list[Path]:
        if v:
            return [Path(p).expanduser() for p in v]
        return []

    def model_post_init(self, __context: Any) -> None:
        if not self.skill_dirs:
            bundled = Path(__file__).parent / "skills"
            user = self.workspace_dir / "skills"
            self.skill_dirs = [bundled, user]

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            _YamlConfigSource(settings_cls),
        )


def load_config(path: Path | None = None) -> JarvisConfig:
    """Load config with YAML + env var layering.

    If *path* is given it is used as the YAML source; otherwise the default
    ~/.jarvis/config.yaml is used.  env vars (JARVIS_*) always win.
    """
    if path is not None:
        # Temporarily override the YAML source path by subclassing.
        class _CustomConfig(JarvisConfig):
            @classmethod
            def settings_customise_sources(
                cls,
                settings_cls: type[BaseSettings],
                init_settings: PydanticBaseSettingsSource,
                env_settings: PydanticBaseSettingsSource,
                dotenv_settings: PydanticBaseSettingsSource,
                file_secret_settings: PydanticBaseSettingsSource,
            ) -> tuple[PydanticBaseSettingsSource, ...]:
                return (
                    init_settings,
                    env_settings,
                    _YamlConfigSource(settings_cls, yaml_path=path),
                )

        cfg = _CustomConfig()
        # Return as plain JarvisConfig so callers get the exact type.
        return JarvisConfig.model_validate(cfg.model_dump())
    return JarvisConfig()
