from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_env: str = "development"
    app_name: str = "safety-vision-agent"
    database_url: str = "sqlite:///./runtime/safety_vision_agent.sqlite3"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    llm_api_base_url: str = ""
    llm_api_key: str = ""
    llm_model_name: str = ""

    vlm_api_base_url: str = ""
    vlm_api_key: str = ""
    vlm_model_name: str = ""
    vlm_timeout_seconds: int = 120

    yolo_api_base_url: str = ""
    yolo_api_key: str = ""
    yolo_timeout_seconds: int = 60
    yolo_confidence_threshold: float = 0.25

    rule_blocks_path: str = "../configs/rules/four_openings_edges_rule_blocks.example.json"

    upload_dir: str = "./runtime/uploads"
    output_dir: str = "./runtime/outputs"
    report_dir: str = "./runtime/reports"
    max_upload_size_mb: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
