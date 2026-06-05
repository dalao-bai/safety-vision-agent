"""Application configuration loaded from environment / .env.

v0.1 keeps configuration centralized here. Required model/API values must be
present or settings loading fails with a clear, actionable error.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the .env at the repository root so the backend finds it regardless of
# the current working directory (e.g. when started from backend/). config.py is
# at <root>/backend/app/core/config.py, so the root is four parents up.
_DEFAULT_ENV_FILE = str(Path(__file__).resolve().parents[3] / ".env")

# Maps internal field names to the environment variable names users actually set.
# Used to produce error messages in terms users recognize.
_ENV_ALIASES = {
    "openai_api_base_url": "OPENAI_API_BASE_URL",
    "openai_api_key": "OPENAI_API_KEY",
    "vlm_model": "VLM_MODEL",
    "agent_model": "AGENT_MODEL",
}


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


class Settings(BaseSettings):
    """Runtime settings for the v0.1 Agent backend."""

    model_config = SettingsConfigDict(
        env_file=_DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Required model / API configuration.
    openai_api_base_url: str = Field(..., alias="OPENAI_API_BASE_URL")
    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    vlm_model: str = Field(..., alias="VLM_MODEL")
    agent_model: str = Field(..., alias="AGENT_MODEL")

    # Optional local-runtime knobs with safe defaults.
    database_path: str = Field("runtime/agent.db", alias="DATABASE_PATH")
    upload_dir: str = Field("runtime/uploads", alias="UPLOAD_DIR")
    max_image_bytes: int = Field(10 * 1024 * 1024, alias="MAX_IMAGE_BYTES")
    max_tool_iterations: int = Field(5, alias="MAX_TOOL_ITERATIONS")


def load_settings(env_file: str | None = ".env") -> Settings:
    """Load settings, converting pydantic validation errors into a clear ConfigError.

    Pass ``env_file=None`` to skip reading any .env file (used by tests so the
    process environment is the only source of truth).
    """
    try:
        return Settings(_env_file=env_file)  # type: ignore[call-arg]
    except ValidationError as exc:
        missing: list[str] = []
        other: list[str] = []
        for err in exc.errors():
            field = err["loc"][0] if err["loc"] else ""
            env_name = _ENV_ALIASES.get(str(field), str(field))
            if err["type"] == "missing":
                missing.append(env_name)
            else:
                other.append(f"{env_name}: {err['msg']}")

        parts: list[str] = []
        if missing:
            parts.append("missing required configuration: " + ", ".join(missing))
        if other:
            parts.append("invalid configuration: " + "; ".join(other))
        raise ConfigError(
            "Configuration error - " + " | ".join(parts) +
            ". Set these in your environment or .env file (see .env.example)."
        ) from exc


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return cached application settings, loading them on first use."""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings
