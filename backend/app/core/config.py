import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"


def resolve_project_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _read_env_file() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _env(name: str, default: str, env_file: dict[str, str]) -> str:
    return os.getenv(name, env_file.get(name, default))


def _env_int(name: str, default: int, env_file: dict[str, str]) -> int:
    value = _env(name, str(default), env_file)
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float, env_file: dict[str, str]) -> float:
    value = _env(name, str(default), env_file)
    try:
        return float(value)
    except ValueError:
        return default


@dataclass
class Settings:
    app_env: str = "development"
    app_name: str = "safety-vision-agent"
    sqlite_path: str = "runtime/safety_vision_agent.sqlite3"

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
    def database_file_path(self) -> Path:
        return resolve_project_path(self.sqlite_path)

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
    env_file = _read_env_file()
    return Settings(
        app_env=_env("APP_ENV", "development", env_file),
        app_name=_env("APP_NAME", "safety-vision-agent", env_file),
        sqlite_path=_env("SQLITE_PATH", "runtime/safety_vision_agent.sqlite3", env_file),
        llm_api_base_url=_env("LLM_API_BASE_URL", "", env_file),
        llm_api_key=_env("LLM_API_KEY", "", env_file),
        llm_model_name=_env("LLM_MODEL_NAME", "", env_file),
        vlm_api_base_url=_env("VLM_API_BASE_URL", "", env_file),
        vlm_api_key=_env("VLM_API_KEY", "", env_file),
        vlm_model_name=_env("VLM_MODEL_NAME", "", env_file),
        vlm_timeout_seconds=_env_int("VLM_TIMEOUT_SECONDS", 120, env_file),
        yolo_api_base_url=_env("YOLO_API_BASE_URL", "", env_file),
        yolo_api_key=_env("YOLO_API_KEY", "", env_file),
        yolo_timeout_seconds=_env_int("YOLO_TIMEOUT_SECONDS", 60, env_file),
        yolo_confidence_threshold=_env_float("YOLO_CONFIDENCE_THRESHOLD", 0.25, env_file),
        rule_blocks_path=_env("RULE_BLOCKS_PATH", "configs/rules/four_openings_edges_rule_blocks.example.json", env_file),
        upload_dir=_env("UPLOAD_DIR", "./runtime/uploads", env_file),
        output_dir=_env("OUTPUT_DIR", "./runtime/outputs", env_file),
        report_dir=_env("REPORT_DIR", "./runtime/reports", env_file),
        max_upload_size_mb=_env_int("MAX_UPLOAD_SIZE_MB", 20, env_file),
    )
