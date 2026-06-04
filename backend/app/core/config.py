from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def resolve_project_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


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

    rule_blocks_path: str = "configs/rules/four_openings_edges_rule_blocks.example.json"

    upload_dir: str = "./runtime/uploads"
    output_dir: str = "./runtime/outputs"
    report_dir: str = "./runtime/reports"
    max_upload_size_mb: int = 20

    @property
    def sqlalchemy_database_url(self) -> str:
        db_path = self.database_file_path
        if not db_path:
            return self.database_url
        return f"sqlite:///{db_path.as_posix()}"

    @property
    def database_file_path(self) -> Path | None:
        if not self.database_url.startswith("sqlite:///"):
            return None
        raw_path = self.database_url.removeprefix("sqlite:///")
        if raw_path == ":memory:":
            return None
        return resolve_project_path(raw_path)

    @property
    def upload_path(self) -> Path:
        return resolve_project_path(self.upload_dir)

    @property
    def output_path(self) -> Path:
        return resolve_project_path(self.output_dir)

    @property
    def report_path(self) -> Path:
        return resolve_project_path(self.report_dir)

    @property
    def rule_blocks_file_path(self) -> Path:
        return resolve_project_path(self.rule_blocks_path)


@lru_cache
def get_settings() -> Settings:
    return Settings()
