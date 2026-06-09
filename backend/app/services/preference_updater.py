"""用户偏好记忆更新（第二层记忆，v0.2）。

从 user_hazard_stats 确定性地汇总出用户关注的隐患类型，并（可选）调用一个
可注入的摘要 callable 生成不超过 100 字的偏好摘要，最后增量写回
user_preferences。作为 BackgroundTask 运行，任何失败都吞掉并保留旧偏好，
绝不向上冒泡异常。
"""

from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from typing import Any, Callable

from app.db import repositories as repo
from app.services.responses_client import ResponsesClient

logger = logging.getLogger(__name__)

# 提取关注隐患类型的数量上限，避免偏好画像过于发散。
_TOP_N = 5
# 偏好摘要的字符上限（中文按字计）。
_SUMMARY_MAX_CHARS = 100


def _top_hazard_types(stats: list[dict[str, Any]], top_n: int = _TOP_N) -> list[str]:
    """按 hazard_type 聚合 occurrence_count，返回出现次数最高的前若干类型。

    同一 hazard_type 可能跨多个 risk_level 拆成多行，这里先合并求和；
    次数相同的，按类型名排序保证结果确定。
    """
    totals: dict[str, int] = defaultdict(int)
    for row in stats:
        hazard_type = row.get("hazard_type")
        if not hazard_type:
            continue
        totals[hazard_type] += int(row.get("occurrence_count") or 0)
    # 先按次数降序，再按类型名升序，保证确定性。
    ordered = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    return [hazard_type for hazard_type, _ in ordered[:top_n]]


def _local_summary(top_types: list[str]) -> str:
    """无摘要 callable 时的确定性本地兜底摘要。"""
    if not top_types:
        return "暂无足够数据归纳用户关注重点。"
    summary = "用户主要关注的隐患类型：" + "、".join(top_types) + "。"
    return summary[:_SUMMARY_MAX_CHARS]


def update_user_preferences(
    conn: sqlite3.Connection,
    user_id: str,
    summarize_fn: Callable[[list[dict[str, Any]]], str] | None = None,
) -> None:
    """根据隐患统计增量更新用户偏好。后台任务，失败不抛异常。

    - focus_hazard_types：从统计里确定性取出现次数最高的前若干类型。
    - preference_summary：有 summarize_fn 则用它生成（截断到 100 字），
      否则用本地确定性兜底。
    - frequent_questions：本函数不动，保留原值（不传给 upsert）。
    """
    try:
        stats = repo.get_hazard_stats_by_user(conn, user_id)
        top_types = _top_hazard_types(stats)

        if summarize_fn is not None:
            try:
                summary = summarize_fn(stats)
            except Exception:  # noqa: BLE001 - 摘要失败不应影响类型更新
                logger.exception("summarize_fn 生成偏好摘要失败，回退到本地摘要 user_id=%s", user_id)
                summary = _local_summary(top_types)
        else:
            summary = _local_summary(top_types)

        summary = (summary or "")[:_SUMMARY_MAX_CHARS]

        # 只传要更新的字段；frequent_questions 不传，由 upsert 保留原值。
        repo.upsert_preferences(
            conn,
            user_id,
            preference_summary=summary,
            focus_hazard_types=top_types,
        )
    except Exception:  # noqa: BLE001 - 后台任务整体兜底，保留旧偏好
        logger.exception("更新用户偏好失败，保留旧值 user_id=%s", user_id)


def build_summarize_fn(
    client: ResponsesClient, model: str
) -> Callable[[list[dict[str, Any]]], str]:
    """生产用工厂：返回一个用 ResponsesClient 生成偏好摘要的 callable。

    返回的 callable 接受隐患统计列表，调用模型产出一句不超过 100 字的中文摘要。
    """

    def _summarize(stats: list[dict[str, Any]]) -> str:
        lines = [
            f"- {row.get('hazard_type')}（{row.get('risk_level')}）出现 "
            f"{row.get('occurrence_count')} 次"
            for row in stats
        ]
        stats_text = "\n".join(lines) if lines else "（暂无统计）"
        input_items = [
            {
                "role": "system",
                "content": "你是施工安全助手。根据用户历史隐患统计，用一句不超过100字的中文"
                "概括该用户最关注的安全隐患方向，只输出摘要本身。",
            },
            {"role": "user", "content": f"以下是用户的隐患统计：\n{stats_text}"},
        ]
        result = client.create(model=model, input_items=input_items)
        return (result.text or "").strip()

    return _summarize
