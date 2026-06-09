"""Tests for annotation.db repository (v0.2)."""

from __future__ import annotations

import sqlite3

import pytest

from app.db.annotation import (
    connect_annotation,
    create_annotation_item,
    get_annotation_item,
    list_annotation_items,
    mark_exported,
    set_error_type,
)

_SAMPLE_ANALYSIS = {
    "summary": "存在临边防护缺失",
    "hazards": [{"name": "临边坠落", "risk_level": "high"}],
}


@pytest.fixture
def aconn(tmp_path):
    db_path = tmp_path / "annotation.db"
    conn = connect_annotation(str(db_path))
    yield conn
    conn.close()


# --- schema ----------------------------------------------------------------

def test_init_creates_annotation_items_table(aconn):
    cur = aconn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row["name"] for row in cur.fetchall()}
    assert "annotation_items" in tables


# --- create ----------------------------------------------------------------

def test_create_annotation_item_returns_id(aconn):
    aid = create_annotation_item(
        aconn,
        source_conversation_id="conv-1",
        image_id=101,
        user_id="user-a",
        username="alice",
        image_path="uploads/user-a/abc.jpg",
        image_filename="abc.jpg",
        mime_type="image/jpeg",
        analysis=_SAMPLE_ANALYSIS,
    )
    assert aid  # 非空字符串


def test_analysis_json_roundtrips_chinese(aconn):
    create_annotation_item(
        aconn, "conv-1", 1, "u1", "alice",
        "uploads/u1/a.jpg", "a.jpg", "image/jpeg",
        {"summary": "临边防护缺失", "hazards": []},
    )
    item = get_annotation_item(aconn, _last_id(aconn), "u1")
    assert item["analysis_json"]["summary"] == "临边防护缺失"


# --- get -------------------------------------------------------------------

def test_get_annotation_item_wrong_user_returns_none(aconn):
    create_annotation_item(
        aconn, "conv-1", 10, "user-a", "alice",
        "uploads/user-a/a.jpg", "a.jpg", "image/jpeg", _SAMPLE_ANALYSIS,
    )
    aid = _last_id(aconn)
    assert get_annotation_item(aconn, aid, "user-b") is None  # 越权返回 None


def test_get_annotation_item_by_owner(aconn):
    create_annotation_item(
        aconn, "conv-2", 20, "user-a", "alice",
        "uploads/user-a/b.jpg", "b.jpg", "image/jpeg", _SAMPLE_ANALYSIS,
    )
    aid = _last_id(aconn)
    item = get_annotation_item(aconn, aid, "user-a")
    assert item is not None
    assert item["image_id"] == 20


# --- unique constraint -----------------------------------------------------

def test_duplicate_image_id_raises(aconn):
    create_annotation_item(
        aconn, "conv-1", 999, "u1", "alice",
        "p.jpg", "p.jpg", "image/jpeg", {},
    )
    with pytest.raises(sqlite3.IntegrityError):
        create_annotation_item(
            aconn, "conv-2", 999, "u1", "alice",
            "p.jpg", "p.jpg", "image/jpeg", {},
        )


# --- list ------------------------------------------------------------------

def test_list_annotation_items_filtered_by_user(aconn):
    create_annotation_item(aconn, "c1", 1, "ua", "alice", "p", "p", "image/jpeg", {})
    create_annotation_item(aconn, "c2", 2, "ub", "bob",   "p", "p", "image/jpeg", {})
    assert len(list_annotation_items(aconn, "ua")) == 1
    assert len(list_annotation_items(aconn, "ub")) == 1


def test_list_filters_exported(aconn):
    create_annotation_item(aconn, "c1", 1, "ua", "a", "p", "p", "image/jpeg", {})
    create_annotation_item(aconn, "c2", 2, "ua", "a", "p", "p", "image/jpeg", {})
    aid = _last_id(aconn)
    mark_exported(aconn, [aid], "ua")

    assert len(list_annotation_items(aconn, "ua", exported=False)) == 1
    assert len(list_annotation_items(aconn, "ua", exported=True)) == 1
    assert len(list_annotation_items(aconn, "ua", exported=None)) == 2


# --- mark_exported ---------------------------------------------------------

def test_mark_exported_returns_count(aconn):
    create_annotation_item(aconn, "c1", 1, "ua", "a", "p", "p", "image/jpeg", {})
    create_annotation_item(aconn, "c2", 2, "ua", "a", "p", "p", "image/jpeg", {})
    ids = [r["id"] for r in aconn.execute(
        "SELECT id FROM annotation_items WHERE user_id='ua'"
    ).fetchall()]
    count = mark_exported(aconn, ids, "ua")
    assert count == 2


def test_mark_exported_wrong_user_no_effect(aconn):
    create_annotation_item(aconn, "c1", 1, "ua", "a", "p", "p", "image/jpeg", {})
    aid = _last_id(aconn)
    count = mark_exported(aconn, [aid], "ub")  # 越权
    assert count == 0
    item = get_annotation_item(aconn, aid, "ua")
    assert item["exported_at"] is None


def test_mark_exported_empty_list(aconn):
    assert mark_exported(aconn, [], "ua") == 0


# --- set_error_type --------------------------------------------------------

def test_set_error_type_updates_field(aconn):
    create_annotation_item(aconn, "c1", 1, "ua", "a", "p", "p", "image/jpeg", {})
    aid = _last_id(aconn)
    ok = set_error_type(aconn, aid, "ua", "漏检")
    assert ok is True
    item = get_annotation_item(aconn, aid, "ua")
    assert item["error_type"] == "漏检"


def test_set_error_type_to_none(aconn):
    create_annotation_item(aconn, "c1", 1, "ua", "a", "p", "p", "image/jpeg", {})
    aid = _last_id(aconn)
    set_error_type(aconn, aid, "ua", "误报")
    set_error_type(aconn, aid, "ua", None)  # 标记为准确
    item = get_annotation_item(aconn, aid, "ua")
    assert item["error_type"] is None


def test_set_error_type_wrong_user_returns_false(aconn):
    create_annotation_item(aconn, "c1", 1, "ua", "a", "p", "p", "image/jpeg", {})
    aid = _last_id(aconn)
    ok = set_error_type(aconn, aid, "ub", "漏检")  # 越权
    assert ok is False


# --- helper ----------------------------------------------------------------

def _last_id(conn) -> str:
    return conn.execute(
        "SELECT id FROM annotation_items ORDER BY rowid DESC LIMIT 1"
    ).fetchone()["id"]
