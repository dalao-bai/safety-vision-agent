# backend/app/models/foe_schemas.py
"""四口五临边微调模型的输出契约 + 报告检索结果类型。

与旧 app/models/schemas.py 的 AnalysisResult 并存：本文件是新 schema 的落地起点，
将来 analyze_image 换微调模型后产出 FoeAnalysis。本期仅供报告/检索消费。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReasoningStep(BaseModel):
    """思维链一步：observe / locate / match_rule / assess。"""
    step: str
    content: str


class FoeObject(BaseModel):
    """一个被识别的四口五临边对象及其隐患判定。多余字段(如 scene)忽略。"""
    model_config = ConfigDict(extra="ignore")

    related_object: str
    object_bbox: list[int] = Field(default_factory=list)
    status: str  # confirmed_hazard | safe | uncertain
    hazard_type_id: str | None = None
    hazard_type: str | None = None
    visual_evidence: str = ""
    rule_basis: str | None = None
    evidence_sufficiency: str | None = None
    uncertainty_reason: str | None = None
    reasoning_chain: list[ReasoningStep] = Field(default_factory=list)


class FoeAnalysis(BaseModel):
    """一张图的分析结果：一图多对象。"""
    image_ref: str | None = None
    width: int | None = None
    height: int | None = None
    objects: list[FoeObject] = Field(default_factory=list)


class ClauseRef(BaseModel):
    """检索到的官方条款引用。"""
    standard_code: str          # 如 "JGJ 80-2016"
    clause_id: str              # 如 "第4.1.1条"
    official_text: str          # 标准原文
    paraphrase: str | None = None   # rule_blocks 的 rule_text（口径摘要）
    source_raw: str = ""        # 原始 source 串，便于溯源


class FoeReportRequest(BaseModel):
    """报告生成请求体。"""
    analyses: list[FoeAnalysis] = Field(default_factory=list)
    title: str | None = None
