"""认证登录路由测试（v0.2）。

用 TestClient + dependency_overrides 把 DB 换成临时 SQLite，不依赖网络。
覆盖：首次登录自动注册、二次登录密钥正确、密钥错误 401、token 可解码还原 sub。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import dependencies as deps
from app.api.routes.auth import router as auth_router
from app.core.config import get_settings
from app.db.sqlite import connect, init_db
from app.services.security import decode_access_token


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "auth.db"

    app = FastAPI()
    app.include_router(auth_router)

    def _override_db():
        conn = connect(str(db_path))
        init_db(conn)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[deps.get_db] = _override_db
    app.dependency_overrides[deps.get_app_settings] = get_settings

    yield TestClient(app)


def test_first_login_auto_registers_and_returns_token(client):
    resp = client.post(
        "/api/auth/login",
        json={"username": "alice", "api_key": "key-alice"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"]
    assert body["user_id"]
    assert body["username"] == "alice"


def test_second_login_same_key_succeeds(client):
    first = client.post(
        "/api/auth/login",
        json={"username": "bob", "api_key": "key-bob"},
    )
    uid = first.json()["user_id"]

    second = client.post(
        "/api/auth/login",
        json={"username": "bob", "api_key": "key-bob"},
    )
    assert second.status_code == 200
    # 同一用户再次登录拿到同一 user_id。
    assert second.json()["user_id"] == uid


def test_wrong_key_returns_401(client):
    client.post(
        "/api/auth/login",
        json={"username": "carol", "api_key": "key-carol"},
    )
    resp = client.post(
        "/api/auth/login",
        json={"username": "carol", "api_key": "wrong-key"},
    )
    assert resp.status_code == 401


def test_token_decodes_to_correct_subject(client):
    resp = client.post(
        "/api/auth/login",
        json={"username": "dave", "api_key": "key-dave"},
    )
    body = resp.json()
    settings = get_settings()
    payload = decode_access_token(
        body["token"], settings.jwt_secret, settings.jwt_algorithm
    )
    assert payload["sub"] == body["user_id"]
    assert payload["username"] == "dave"
