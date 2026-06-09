"""Pytest configuration for the backend test suite.

Sets placeholder model/API configuration before any test module is collected,
so importing ``app.main`` (which validates config at import time) succeeds.
Tests that exercise real behavior override the Agent/VLM clients with fakes,
so these values are never used to make network calls.

test_config.py manages its own environment via monkeypatch and is unaffected.
"""

from __future__ import annotations

import os

os.environ.setdefault("OPENAI_API_BASE_URL", "https://api.test.local/v1")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder")
os.environ.setdefault("VLM_MODEL", "test-vlm")
os.environ.setdefault("AGENT_MODEL", "test-agent")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-placeholder")
