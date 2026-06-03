from datetime import datetime
from pydantic import BaseModel, Field


BBox = list[float]


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str
    image_path: str | None = None
    selected_bbox: BBox | None = None


class HazardObject(BaseModel):
    object_id: str
    object_name: str
    bbox: BBox
    status: str
    hazard_type_id: str | None = None
    hazard_type: str | None = None
    visual_evidence: str
    missing_evidence: str | None = None
    evidence_sufficiency: str = "sufficient"
    uncertainty_reason: str | None = None
    rule: str
    confidence: float | None = None


class UncertaintyFollowUp(BaseModel):
    object_name: str
    bbox: BBox | None = None
    uncertainty_reason: str
    missing_evidence: str
    follow_up_question: str
    capture_suggestion: str


class VLMAnalysisResult(BaseModel):
    objects: list[HazardObject] = Field(default_factory=list)
    summary: str = ""


class Detection(BaseModel):
    label: str
    bbox: BBox
    confidence: float


class YOLODetectionResult(BaseModel):
    detections: list[Detection] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)


class FusedResult(BaseModel):
    hazards: list[HazardObject] = Field(default_factory=list)
    detections: list[Detection] = Field(default_factory=list)
    uncertain_items: list[HazardObject] = Field(default_factory=list)
    uncertain_followups: list[UncertaintyFollowUp] = Field(default_factory=list)
    summary: str = ""
    recommendations: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    fused_result: FusedResult | None = None
    tool_calls: list[dict] = Field(default_factory=list)


class UploadedImageResponse(BaseModel):
    file_id: str
    filename: str
    path: str


class AnalysisRequest(BaseModel):
    conversation_id: str | None = None
    image_path: str
    message: str = "分析这张图中的施工安全隐患。"
    selected_bbox: BBox | None = None


class AnalysisResponse(BaseModel):
    analysis_id: str
    conversation_id: str
    task_id: str
    status: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: dict | None = None
    error: str | None = None


class AnalysisResultResponse(BaseModel):
    analysis_id: str
    status: str
    result: FusedResult | None = None


class ReviewCreateRequest(BaseModel):
    analysis_id: str
    item_type: str = "hazard"
    item_index: int
    decision: str
    reviewer: str | None = None
    revised_json: dict = Field(default_factory=dict)
    note: str = ""


class ReviewResponse(BaseModel):
    review_id: str
    analysis_id: str
    decision: str
    note: str = ""


class RemediationCreateRequest(BaseModel):
    conversation_id: str | None = None
    analysis_id: str
    hazard_index: int
    title: str
    recommendation: str
    responsible_person: str | None = None
    due_at: datetime | None = None
    hazard_json: dict = Field(default_factory=dict)


class RemediationResponse(BaseModel):
    task_id: str
    analysis_id: str
    status: str
    title: str
    recommendation: str


class RemediationEvidenceRequest(BaseModel):
    image_path: str
    note: str = ""


class RemediationVerifyRequest(BaseModel):
    decision: str
    note: str = ""


class ReportRequest(BaseModel):
    conversation_id: str
    title: str = "施工现场安全隐患识别报告"
    fused_result: FusedResult | None = None


class ReportResponse(BaseModel):
    title: str
    markdown: str
