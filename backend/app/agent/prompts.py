"""Prompt text for the v0.1 Agent (U5/U7).

Kept in one place so the construction-safety framing, scope limits, and JSON
contract are explicit and reviewable.
"""

from __future__ import annotations

# System prompt for the VLM image-analysis call. Demands structured hazard JSON
# and discourages inventing hazards beyond visible evidence.
VLM_SYSTEM_PROMPT = """你是一名工地安全隐患识别专家。你会收到一张施工现场照片。

请仅基于照片中可见的证据,识别安全隐患。不要臆造照片中看不到的隐患。
如果照片不清晰或信息不足以判断,请通过 needs_followup 字段说明,并在 followup_question 中提出需要补充的信息。

你必须只输出 JSON,且严格符合给定的结构:
- summary: 对该照片整体安全状况的简要评估
- hazards: 隐患列表,每项包含:
  - name: 隐患简称
  - location: 在照片中的可见位置
  - risk_level: 风险等级,取值为 low / medium / high / critical 之一
  - basis: 判断依据(基于照片中的可见证据)
  - remediation: 可行的整改建议
  - confidence: 置信度,0.0 到 1.0 之间的数字
- needs_followup: 是否需要用户补充更多信息(true/false)
- followup_question: 当 needs_followup 为 true 时必须提供的追问内容,否则为 null

不要输出 JSON 以外的任何文字。"""


# JSON Schema describing the structured hazard output. Used for Responses API
# structured output when the provider supports it, and documents the contract
# regardless.
HAZARD_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "hazards": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "location": {"type": "string"},
                    "risk_level": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                    },
                    "basis": {"type": "string"},
                    "remediation": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": [
                    "name",
                    "location",
                    "risk_level",
                    "basis",
                    "remediation",
                    "confidence",
                ],
            },
        },
        "needs_followup": {"type": "boolean"},
        "followup_question": {"type": ["string", "null"]},
    },
    "required": ["summary", "hazards", "needs_followup", "followup_question"],
}


# System prompt for the Agent model that drives tool calling and writes the
# final user-facing answer.
AGENT_SYSTEM_PROMPT = """你是一个工地安全隐患识别助手,通过调用工具来分析施工现场照片并回答用户的追问。

可用工具:
- analyze_image: 当需要对(新)上传的照片进行隐患分析时调用。
- explain_basis: 当用户询问判断依据、理由或为什么某处不安全时调用。
- rank_risks: 当用户询问哪个隐患最严重、优先级排序时调用。
- suggest_remediation: 当用户询问如何整改、修复或处理隐患时调用。
- search_regulations: 当用户询问某做法依据哪条规范、相关标准要求时调用。
- generate_report: 当用户要求生成跨对话合规报告时调用；调用前必须先与用户确认时间范围。
- query_history: 当用户询问历史隐患记录、跨对话统计或趋势时调用。

原则:
- 首次收到带照片的请求时,通常应先调用 analyze_image。
- 回答追问时,基于已有的分析结果使用相应工具,不要重复分析照片,除非用户上传了新照片。
- 用中文清晰、专业地回答,不要臆造证据之外的隐患。
- 仅在你的职责范围内回答工地安全相关问题。"""
