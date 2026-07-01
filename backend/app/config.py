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
    embedding_api_base_url: str | None = None
    embedding_api_key: str | None = None
    # chunking
    chunk_max_chars: int = 800
    chunk_overlap_chars: int = 100
    # retrieval
    retrieval_top_k_dense: int = 20
    retrieval_top_k_bm25: int = 20
    retrieval_rrf_k: int = 60
    retrieval_final_k: int = 5
    # reranker
    reranker_model: str = "BAAI/bge-reranker-base"
    reranker_enabled: bool = True

    # runtime
    database_path: str = "runtime/agent.db"
    upload_dir: str = "runtime/uploads"
    report_dir: str = "runtime/reports"
    pipeline_intake_dir: str = "runtime/pipeline_intake"
    max_image_bytes: int = 10 * 1024 * 1024
    max_tool_iterations: int = 5
    max_vlm_workers: int = 4
    max_context_chars: int = 80_000
    tool_loop_timeout_seconds: int = 30
    # "simple" 先跑通；"full" 启用完整飞轮字段（微调模型就绪后切换）
    vlm_instruction_mode: str = "simple"
    # LLM 原始调用日志（每 session 一个 JSONL），空字符串则禁用
    agent_debug_dir: str = "runtime/debug"

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
