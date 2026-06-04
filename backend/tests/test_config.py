import sys

from app.core.config import PROJECT_ROOT, get_settings


def test_default_settings_resolve_project_paths(monkeypatch) -> None:
    monkeypatch.delenv("SQLITE_PATH", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.database_file_path == PROJECT_ROOT / "runtime/safety_vision_agent.sqlite3"
    assert settings.upload_path == PROJECT_ROOT / "runtime/uploads"
    assert settings.output_path == PROJECT_ROOT / "runtime/outputs"
    assert settings.report_path == PROJECT_ROOT / "runtime/reports"
    assert settings.rule_blocks_file_path == PROJECT_ROOT / "configs/rules/four_openings_edges_rule_blocks.example.json"


def test_environment_overrides_do_not_need_pydantic_settings(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "agent.sqlite3"
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("SQLITE_PATH", db_path.as_posix())
    monkeypatch.setenv("UPLOAD_DIR", upload_dir.as_posix())
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.database_file_path == db_path
    assert settings.upload_path == upload_dir
    assert "pydantic_settings" not in sys.modules
