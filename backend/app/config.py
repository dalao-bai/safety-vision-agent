from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # shared OpenAI-compatible config
    openai_api_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = "sk-missing"
    agent_model: str = "gpt-4o"

    # VLM (local vLLM); falls back to shared config when not set
    vlm_model: str = "gpt-4o"
    vlm_api_base_url: str | None = None
    vlm_api_key: str | None = None

    # RAG
    embedding_model: str = "text-embedding-3-small"
    chroma_dir: str = "runtime/chroma"

    # runtime
    database_path: str = "runtime/agent.db"
    upload_dir: str = "runtime/uploads"
    report_dir: str = "runtime/reports"
    pipeline_intake_dir: str = "runtime/pipeline_intake"
    max_image_bytes: int = 10 * 1024 * 1024
    max_tool_iterations: int = 5
    max_vlm_workers: int = 4

    @model_validator(mode="after")
    def _fill_vlm(self) -> "Settings":
        if not self.vlm_api_base_url:
            self.vlm_api_base_url = self.openai_api_base_url
        if not self.vlm_api_key:
            self.vlm_api_key = self.openai_api_key
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
