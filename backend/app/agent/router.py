from app.services.memory import latest_result_context, resolve_hazard_index


def classify_intent(message: str, conversation_id: str, has_image: bool) -> str:
    text = message.strip().lower()
    has_memory = bool(latest_result_context(conversation_id))

    if any(keyword in text for keyword in ["报告", "生成报表", "导出"]):
        return "report" if has_memory else "need_image"
    if any(keyword in text for keyword in ["整改", "整改任务", "怎么处理", "怎么改"]):
        return "remediation" if has_memory else "need_image"
    if any(keyword in text for keyword in ["依据", "规则", "规范", "为什么", "原因"]):
        return "rule_basis" if has_memory else "need_image"
    if any(keyword in text for keyword in ["补拍", "补什么", "证据不足", "还需要什么"]):
        return "evidence_gap" if has_memory else "need_image"
    if has_image and any(keyword in text for keyword in ["分析", "识别", "隐患", "安全帽", "这张图", "图片"]):
        return "analyze"
    if has_memory:
        return "memory_answer"
    return "analyze" if has_image else "need_image"


def route_after_classification(state: dict) -> str:
    return state.get("intent") or "need_image"


def selected_hazard_index(message: str) -> int:
    return resolve_hazard_index(message)
