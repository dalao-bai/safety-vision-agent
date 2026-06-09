"""Tests for application configuration loading and validation (U1)."""

from __future__ import annotations

import pytest

from app.core.config import ConfigError, load_settings

_REQUIRED = {
    "OPENAI_API_BASE_URL": "https://api.example.com/v1",
    "OPENAI_API_KEY": "sk-test-key",
    "VLM_MODEL": "test-vlm",
    "AGENT_MODEL": "test-agent",
    "JWT_SECRET": "test-jwt-secret",
}


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """Ensure none of the required vars leak in from the real environment."""
    for key in _REQUIRED:
        monkeypatch.delenv(key, raising=False)
    yield


def test_loads_when_all_required_vars_present(monkeypatch):
    for key, value in _REQUIRED.items():
        monkeypatch.setenv(key, value)

    settings = load_settings(env_file=None)

    assert settings.openai_api_base_url == _REQUIRED["OPENAI_API_BASE_URL"]
    assert settings.openai_api_key == _REQUIRED["OPENAI_API_KEY"]
    assert settings.vlm_model == _REQUIRED["VLM_MODEL"]
    assert settings.agent_model == _REQUIRED["AGENT_MODEL"]


def test_missing_api_key_reports_clear_error(monkeypatch):
    for key, value in _REQUIRED.items():
        if key != "OPENAI_API_KEY":
            monkeypatch.setenv(key, value)

    with pytest.raises(ConfigError) as exc_info:
        load_settings(env_file=None)

    assert "OPENAI_API_KEY" in str(exc_info.value)
    assert "missing" in str(exc_info.value).lower()


def test_missing_vlm_model_reports_which_field(monkeypatch):
    for key, value in _REQUIRED.items():
        if key != "VLM_MODEL":
            monkeypatch.setenv(key, value)

    with pytest.raises(ConfigError) as exc_info:
        load_settings(env_file=None)

    assert "VLM_MODEL" in str(exc_info.value)


def test_missing_agent_model_reports_which_field(monkeypatch):
    for key, value in _REQUIRED.items():
        if key != "AGENT_MODEL":
            monkeypatch.setenv(key, value)

    with pytest.raises(ConfigError) as exc_info:
        load_settings(env_file=None)

    assert "AGENT_MODEL" in str(exc_info.value)


def test_optional_values_have_defaults(monkeypatch):
    for key, value in _REQUIRED.items():
        monkeypatch.setenv(key, value)

    settings = load_settings(env_file=None)

    assert settings.database_path == "runtime/agent.db"
    assert settings.upload_dir == "runtime/uploads"
    assert settings.max_image_bytes == 10 * 1024 * 1024
    assert settings.max_tool_iterations == 5
