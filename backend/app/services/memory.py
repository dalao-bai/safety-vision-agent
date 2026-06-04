import re

from app.db import repositories
from app.models.schemas import FusedResult


CHINESE_INDEX = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def recent_messages(conversation_id: str, limit: int = 20) -> list[dict]:
    return [dict(item) for item in repositories.list_messages(conversation_id, limit)]


def latest_result_context(conversation_id: str) -> dict:
    latest = repositories.latest_fused_result_for_conversation(conversation_id)
    if not latest:
        return {}
    analysis, fused = latest
    return {
        "analysis": dict(analysis),
        "fused_result": fused.result_json,
        "result": FusedResult.model_validate(fused.result_json),
    }


def resolve_hazard_index(message: str, default: int = 0) -> int:
    match = re.search(r"第\s*(\d+)\s*个", message)
    if match:
        return max(int(match.group(1)) - 1, 0)
    match = re.search(r"第\s*([一二两三四五六七八九十])\s*个", message)
    if match:
        return max(CHINESE_INDEX.get(match.group(1), 1) - 1, 0)
    return default


def hazard_by_index(conversation_id: str, message: str) -> dict:
    context = latest_result_context(conversation_id)
    result: FusedResult | None = context.get("result")
    if not result:
        return {}
    index = resolve_hazard_index(message)
    if index >= len(result.hazards):
        return {"index": index, "error": "hazard_index_out_of_range", "hazard_count": len(result.hazards)}
    return {
        "index": index,
        "analysis": context["analysis"],
        "hazard": result.hazards[index].model_dump(),
        "fused_result": result.model_dump(),
    }


def latest_uploaded_image_path(conversation_id: str) -> str | None:
    uploaded = repositories.latest_uploaded_file(conversation_id)
    return uploaded.stored_path if uploaded else None
