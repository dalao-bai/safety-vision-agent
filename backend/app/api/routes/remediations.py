from fastapi import APIRouter, HTTPException

from app.db.repositories import (
    add_remediation_evidence,
    create_remediation_task,
    get_remediation_task,
    latest_fused_result,
    update_remediation_status,
)
from app.models.schemas import (
    FusedResult,
    RemediationCreateRequest,
    RemediationEvidenceRequest,
    RemediationResponse,
    RemediationVerifyRequest,
)


router = APIRouter()


def _validate_hazard_target(request: RemediationCreateRequest) -> None:
    record = latest_fused_result(request.analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="analysis result not found")
    fused = FusedResult.model_validate(record.result_json)
    if request.hazard_index < 0 or request.hazard_index >= len(fused.hazards):
        raise HTTPException(status_code=400, detail="hazard_index out of range")


@router.post("", response_model=RemediationResponse)
def create_remediation(request: RemediationCreateRequest) -> RemediationResponse:
    _validate_hazard_target(request)
    task = create_remediation_task(
        conversation_id=request.conversation_id,
        analysis_id=request.analysis_id,
        hazard_index=request.hazard_index,
        title=request.title,
        recommendation=request.recommendation,
        responsible_person=request.responsible_person,
        due_at=request.due_at,
        hazard_json=request.hazard_json,
    )
    return RemediationResponse(
        task_id=task.id,
        analysis_id=task.analysis_id,
        status=task.status,
        title=task.title,
        recommendation=task.recommendation,
    )


@router.post("/{task_id}/evidence")
def submit_remediation_evidence(task_id: str, request: RemediationEvidenceRequest) -> dict[str, str]:
    task = get_remediation_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="remediation task not found")
    evidence = add_remediation_evidence(task_id=task_id, image_path=request.image_path, note=request.note)
    return {"evidence_id": evidence.id, "task_id": task_id, "status": "submitted"}


@router.post("/{task_id}/verify", response_model=RemediationResponse)
def verify_remediation(task_id: str, request: RemediationVerifyRequest) -> RemediationResponse:
    status = "verified" if request.decision == "accept" else "rejected"
    task = update_remediation_status(task_id=task_id, status=status)
    if not task:
        raise HTTPException(status_code=404, detail="remediation task not found")
    return RemediationResponse(
        task_id=task.id,
        analysis_id=task.analysis_id,
        status=task.status,
        title=task.title,
        recommendation=task.recommendation,
    )
