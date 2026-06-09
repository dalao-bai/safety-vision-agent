"""历史查询 + 待标注导出路由测试（任务 E）。

使用 FastAPI TestClient + dependency_overrides：
- get_db / get_annotation_conn 指向临时 SQLite 文件
- get_current_user 返回固定 CurrentUser

不依赖网络。自行 include_router 构造最小 app。
"""

from __future__ import annotations

import csv
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import dependencies as deps
from app.api import auth_deps
from app.api.auth_deps import CurrentUser, get_annotation_conn, get_current_user
from app.api.routes.annotation import router as annotation_router
from app.api.routes.history import router as history_router
from app.db import annotation as anno
from app.db import repositories as repo
from app.db.sqlite import connect, init_db

_USER = CurrentUser(id="user-1", username="alice")
_OTHER = CurrentUser(id="user-2", username="bob")


def _seed_users(db_path: str) -> None:
    """直接插入固定 id 的用户，满足 conversations.user_id 外键约束。"""
    conn = connect(db_path)
    init_db(conn)
    try:
        for uid, name in (("user-1", "alice"), ("user-2", "bob")):
            conn.execute(
                "INSERT OR IGNORE INTO users (id, username, api_key_hash, created_at) "
                "VALUES (?, ?, ?, ?)",
                (uid, name, "h", "2026-01-01T00:00:00+00:00"),
            )
        conn.commit()
    finally:
        conn.close()


def _make_app(db_path: str, anno_path: str, user: CurrentUser) -> FastAPI:
    app = FastAPI()
    app.include_router(history_router)
    app.include_router(annotation_router)

    def _override_db():
        conn = connect(db_path)
        init_db(conn)
        try:
            yield conn
        finally:
            conn.close()

    def _override_anno():
        conn = anno.connect_annotation(anno_path)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[deps.get_db] = _override_db
    app.dependency_overrides[auth_deps.get_db] = _override_db
    app.dependency_overrides[get_annotation_conn] = _override_anno
    app.dependency_overrides[get_current_user] = lambda: user
    return app


@pytest.fixture
def paths(tmp_path):
    return str(tmp_path / "main.db"), str(tmp_path / "annotation.db")


# --- /api/history ----------------------------------------------------------

def test_history_returns_user_conversations_and_stats(paths):
    db_path, anno_path = paths

    # 造数据：user-1 两个对话 + 一条统计；user-2 一个对话（不应出现）。
    _seed_users(db_path)
    conn = connect(db_path)
    init_db(conn)
    try:
        repo.create_conversation(conn, "c1", user_id="user-1")
        repo.create_conversation(conn, "c2", user_id="user-1")
        repo.create_conversation(conn, "c3", user_id="user-2")
        repo.upsert_hazard_stat(conn, "user-1", "未系安全带", "high", "c1")
    finally:
        conn.close()

    app = _make_app(db_path, anno_path, _USER)
    client = TestClient(app)

    resp = client.get("/api/history")
    assert resp.status_code == 200
    body = resp.json()

    cids = {c["id"] for c in body["conversations"]}
    assert cids == {"c1", "c2"}  # 只含当前用户，排除 user-2 的 c3
    assert len(body["hazard_stats"]) == 1
    assert body["hazard_stats"][0]["hazard_type"] == "未系安全带"
    assert body["hazard_stats"][0]["occurrence_count"] == 1


def test_history_time_range_filter(paths):
    db_path, anno_path = paths

    _seed_users(db_path)
    conn = connect(db_path)
    init_db(conn)
    try:
        repo.create_conversation(conn, "c1", user_id="user-1")
    finally:
        conn.close()

    app = _make_app(db_path, anno_path, _USER)
    client = TestClient(app)

    # 远未来的 start 应过滤掉所有对话。
    resp = client.get("/api/history", params={"start": "2999-01-01T00:00:00+00:00"})
    assert resp.status_code == 200
    assert resp.json()["conversations"] == []


# --- /api/annotation -------------------------------------------------------

def _seed_annotation(anno_path: str):
    conn = anno.connect_annotation(anno_path)
    try:
        anno.create_annotation_item(
            conn,
            source_conversation_id="c1",
            image_id=101,
            user_id="user-1",
            username="alice",
            image_path="/uploads/a.jpg",
            image_filename="a.jpg",
            mime_type="image/jpeg",
            analysis={"summary": "存在隐患A"},
        )
        anno.create_annotation_item(
            conn,
            source_conversation_id="c3",
            image_id=202,
            user_id="user-2",
            username="bob",
            image_path="/uploads/b.jpg",
            image_filename="b.jpg",
            mime_type="image/png",
            analysis={"summary": "存在隐患B"},
        )
    finally:
        conn.close()


def test_annotation_list_only_current_user(paths):
    db_path, anno_path = paths
    _seed_annotation(anno_path)

    app = _make_app(db_path, anno_path, _USER)
    client = TestClient(app)

    resp = client.get("/api/annotation")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["image_id"] == 101


def test_annotation_export_csv_and_marks_exported(paths):
    db_path, anno_path = paths
    _seed_annotation(anno_path)

    app = _make_app(db_path, anno_path, _USER)
    client = TestClient(app)

    resp = client.get("/api/annotation/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]

    rows = list(csv.reader(io.StringIO(resp.text)))
    header = rows[0]
    assert header == [
        "id",
        "source_conversation_id",
        "image_id",
        "image_filename",
        "mime_type",
        "error_type",
        "created_at",
        "analysis_summary",
    ]
    # 只含当前用户的一条记录。
    data_rows = rows[1:]
    assert len(data_rows) == 1
    row = data_rows[0]
    assert row[header.index("image_id")] == "101"
    assert row[header.index("image_filename")] == "a.jpg"
    assert row[header.index("analysis_summary")] == "存在隐患A"

    # 导出后再查 exported=False 应为空。
    conn = anno.connect_annotation(anno_path)
    try:
        remaining = anno.list_annotation_items(conn, "user-1", exported=False)
    finally:
        conn.close()
    assert remaining == []


def test_annotation_export_empty_when_nothing_pending(paths):
    db_path, anno_path = paths
    _seed_annotation(anno_path)

    app = _make_app(db_path, anno_path, _USER)
    client = TestClient(app)

    # 第一次导出后，第二次应只有表头。
    client.get("/api/annotation/export")
    resp = client.get("/api/annotation/export")
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert len(rows) == 1  # 仅表头
