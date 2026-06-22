import importlib


def test_settings_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_BASE_URL", "http://agent:8000/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("AGENT_MODEL", "agent-x")
    monkeypatch.setenv("VLM_MODEL", "vlm-x")
    monkeypatch.delenv("VLM_API_BASE_URL", raising=False)
    monkeypatch.delenv("VLM_API_KEY", raising=False)

    import app.config as config
    importlib.reload(config)
    s = config.get_settings()

    assert s.agent_model == "agent-x"
    assert s.vlm_model == "vlm-x"
    assert s.vlm_api_base_url == "http://agent:8000/v1"
    assert s.vlm_api_key == "k"
    assert s.max_tool_iterations == 5
    assert s.pipeline_intake_dir.endswith("pipeline_intake")


def test_vlm_endpoint_override(monkeypatch):
    monkeypatch.setenv("OPENAI_API_BASE_URL", "http://agent:8000/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("AGENT_MODEL", "agent-x")
    monkeypatch.setenv("VLM_MODEL", "vlm-x")
    monkeypatch.setenv("VLM_API_BASE_URL", "http://localhost:8001/v1")
    monkeypatch.setenv("VLM_API_KEY", "vk")

    import app.config as config
    importlib.reload(config)
    s = config.get_settings()
    assert s.vlm_api_base_url == "http://localhost:8001/v1"
    assert s.vlm_api_key == "vk"
