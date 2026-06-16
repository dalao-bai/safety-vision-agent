"""Tests for the analysis-confirm endpoint (v0.2, /api/analyses/confirm).

确认流程是前端 UI 直调、不经 LLM 路由的关键端点（审查修正项 #7）。
用 TestClient + dependency_overrides：主库与 annotation.db 用临时文件，
get_current_user 注入固定用户。BackgroundTask（偏好更新）会真实排程，
但因 summarize_fn 调用的模型端点不可达而被 update_user_preferences 内部吞掉，
不影响断言。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api import dependencies as deps
from app.api.auth_deps import CurrentUser, get_annotation_conn, get_current_user
from app.db import annotation as anno
from app.db import repositories as repo
from app.db.sqlite import connect, init_db
from app.main import create_app

_ANALYSIS = {
    "summary": "存在高处作业隐患",
    "hazards": [
        {
            "name": "未系安全带",
            "location": "顶部",
            "risk_level": "high",
            "basis": "无防护",
            "remediation": "佩戴安全带",
            "confidence": 0.9,
        }
    ],
    "needs_followup": False,
    "followup_question": None,
}


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "main.db"
    anno_path = tmp_path / "annotation.db"

    # 预置用户 + 一个绑定该用户、带图片与分析结果的对话。
    seed = connect(str(db_path))
    init_db(seed)
    user_id = repo.create_user(seed, "alice", "hash")
    cid = repo.create_conversation(seed, user_id=user_id)
    image_id = repo.add_uploaded_image(
        seed, cid, str(tmp_path / "x.jpg"), "x.jpg", "image/jpeg", 100
    )
    repo.save_analysis_result(seed, cid, _ANALYSIS, image_id=image_id)
    seed.close()

    test_user = CurrentUser(id=user_id, username="alice")
    app = create_app()

    def _override_db():
        conn = connect(str(db_path))
        init_db(conn)
        try:
            yield conn
        finally:
            conn.close()

    def _override_anno():
        conn = anno.connect_annotation(str(anno_path))
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[deps.get_db] = _override_db
    app.dependency_overrides[get_annotation_conn] = _override_anno
    app.dependency_overrides[get_current_user] = lambda: test_user

    yield TestClient(app), {
        "user_id": user_id,
        "cid": cid,
        "image_id": image_id,
        "db_path": str(db_path),
        "anno_path": str(anno_path),
    }


def test_accurate_confirmation_upserts_hazard_stats(client):
    test_client, ctx = client
    resp = test_client.post(
        "/api/analyses/confirm",
        json={
            "conversation_id": ctx["cid"],
            "image_confirmations": [{"image_id": ctx["image_id"], "accurate": True}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["confirmed"] is True
    assert body["annotation_items_created"] == 0

    # 第三层统计已写入。
    conn = connect(ctx["db_path"])
    init_db(conn)
    try:
        stats = repo.get_hazard_stats_by_user(conn, ctx["user_id"])
    finally:
        conn.close()
    assert any(s["hazard_type"] == "未系安全带" and s["risk_level"] == "high" for s in stats)


def test_inaccurate_confirmation_writes_annotation(client):
    test_client, ctx = client
    resp = test_client.post(
        "/api/analyses/confirm",
        json={
            "conversation_id": ctx["cid"],
            "image_confirmations": [{"image_id": ctx["image_id"], "accurate": False}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["confirmed"] is False
    assert body["annotation_items_created"] == 1

    # annotation.db 收到该图片，且分析 JSON 正确回填。
    aconn = anno.connect_annotation(ctx["anno_path"])
    try:
        items = anno.list_annotation_items(aconn, ctx["user_id"])
    finally:
        aconn.close()
    assert len(items) == 1
    assert items[0]["image_id"] == ctx["image_id"]
    assert items[0]["analysis_json"]["summary"] == "存在高处作业隐患"


def test_confirm_other_users_conversation_returns_404(client):
    test_client, ctx = client
    # 覆盖成另一个用户，确认归属校验拦截越权。
    app = test_client.app
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="someone-else", username="bob"
    )
    resp = test_client.post(
        "/api/analyses/confirm",
        json={
            "conversation_id": ctx["cid"],
            "image_confirmations": [{"image_id": ctx["image_id"], "accurate": True}],
        },
    )
    assert resp.status_code == 404


def test_confirm_ignores_image_from_another_conversation(client):
    """携带不属于本对话的 image_id（即便 conversation_id 是自己的）应被忽略，不越权读写。"""
    test_client, ctx = client
    # 另建一条他人对话 + 图片 + 分析。
    conn = connect(ctx["db_path"])
    init_db(conn)
    other_uid = repo.create_user(conn, "bob", "hash")  # 真实用户，满足外键
    other_cid = repo.create_conversation(conn, user_id=other_uid)
    foreign_image_id = repo.add_uploaded_image(
        conn, other_cid, "/x/y.jpg", "y.jpg", "image/jpeg", 50
    )
    repo.save_analysis_result(conn, other_cid, _ANALYSIS, image_id=foreign_image_id)
    conn.close()

    resp = test_client.post(
        "/api/analyses/confirm",
        json={
            "conversation_id": ctx["cid"],  # 自己拥有的对话
            "image_confirmations": [{"image_id": foreign_image_id, "accurate": False}],
        },
    )
    assert resp.status_code == 200
    # 外部图被忽略：未写入 annotation，未影响统计。
    assert resp.json()["annotation_items_created"] == 0
    aconn = anno.connect_annotation(ctx["anno_path"])
    try:
        items = anno.list_annotation_items(aconn, ctx["user_id"])
    finally:
        aconn.close()
    assert items == []


def test_duplicate_inaccurate_confirmation_is_idempotent(client):
    test_client, ctx = client
    payload = {
        "conversation_id": ctx["cid"],
        "image_confirmations": [{"image_id": ctx["image_id"], "accurate": False}],
    }
    first = test_client.post("/api/analyses/confirm", json=payload)
    second = test_client.post("/api/analyses/confirm", json=payload)
    assert first.json()["annotation_items_created"] == 1
    # 第二次因 UNIQUE(image_id) 幂等跳过，不重复写入。
    assert second.json()["annotation_items_created"] == 0

    aconn = anno.connect_annotation(ctx["anno_path"])
    try:
        items = anno.list_annotation_items(aconn, ctx["user_id"])
    finally:
        aconn.close()
    assert len(items) == 1
