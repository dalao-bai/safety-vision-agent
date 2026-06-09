"""preference_updater 单元测试（网络无关）。

用临时 sqlite 建表，造用户和隐患统计，注入 fake summarize_fn，验证：
- focus_hazard_types 按聚合次数降序取 top 类型；
- preference_summary 等于注入值；
- summarize_fn 抛异常时旧偏好被保留、函数本身不抛。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.db import repositories as repo
from app.services import preference_updater as pu

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "app" / "db" / "schema.sql"


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """内存库 + 真实 schema，行工厂与生产一致。"""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    yield c
    c.close()


def _seed_user(conn: sqlite3.Connection) -> str:
    return repo.create_user(conn, "alice", "hash")


def test_focus_types_sorted_and_summary_injected(conn: sqlite3.Connection):
    user_id = _seed_user(conn)
    # 高空坠落 3 次（跨两个 risk_level 合并），临边洞口 2 次，触电 1 次。
    repo.upsert_hazard_stat(conn, user_id, "高空坠落", "high", "c1")
    repo.upsert_hazard_stat(conn, user_id, "高空坠落", "high", "c2")
    repo.upsert_hazard_stat(conn, user_id, "高空坠落", "critical", "c3")
    repo.upsert_hazard_stat(conn, user_id, "临边洞口", "medium", "c4")
    repo.upsert_hazard_stat(conn, user_id, "临边洞口", "medium", "c5")
    repo.upsert_hazard_stat(conn, user_id, "触电", "low", "c6")

    fixed = "用户高度关注高空作业与临边防护。"
    pu.update_user_preferences(conn, user_id, summarize_fn=lambda stats: fixed)

    prefs = repo.get_preferences(conn, user_id)
    assert prefs is not None
    assert prefs["focus_hazard_types"] == ["高空坠落", "临边洞口", "触电"]
    assert prefs["preference_summary"] == fixed


def test_local_summary_fallback_without_fn(conn: sqlite3.Connection):
    user_id = _seed_user(conn)
    repo.upsert_hazard_stat(conn, user_id, "高空坠落", "high", "c1")

    pu.update_user_preferences(conn, user_id, summarize_fn=None)

    prefs = repo.get_preferences(conn, user_id)
    assert prefs["focus_hazard_types"] == ["高空坠落"]
    assert "高空坠落" in prefs["preference_summary"]


def test_summarize_fn_raises_preserves_old_and_no_throw(conn: sqlite3.Connection):
    user_id = _seed_user(conn)
    # 预置旧偏好。
    repo.upsert_preferences(
        conn,
        user_id,
        preference_summary="旧摘要",
        focus_hazard_types=["旧类型"],
        frequent_questions=["旧问题"],
    )
    repo.upsert_hazard_stat(conn, user_id, "高空坠落", "high", "c1")

    def boom(stats):
        raise RuntimeError("summary backend down")

    # 不应抛异常。
    pu.update_user_preferences(conn, user_id, summarize_fn=boom)

    prefs = repo.get_preferences(conn, user_id)
    # 摘要回退到本地兜底（含统计类型），类型按统计更新。
    assert prefs["focus_hazard_types"] == ["高空坠落"]
    assert "高空坠落" in prefs["preference_summary"]
    # frequent_questions 未被本函数触碰，保留原值。
    assert prefs["frequent_questions"] == ["旧问题"]


def test_summary_truncated_to_100_chars(conn: sqlite3.Connection):
    user_id = _seed_user(conn)
    repo.upsert_hazard_stat(conn, user_id, "高空坠落", "high", "c1")

    long_text = "隐" * 200
    pu.update_user_preferences(conn, user_id, summarize_fn=lambda stats: long_text)

    prefs = repo.get_preferences(conn, user_id)
    assert len(prefs["preference_summary"]) == 100
