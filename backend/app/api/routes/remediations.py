from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.repositories import add_remediation_evidence, create_remediation_task, update_remediation_status
from app.db.session import get_db
from app.models.schemas import (
    RemediationCreateRequest,
    RemediationEvidenceRequest,
    RemediationResponse,
    RemediationVerifyRequest,
)


router = APIRouter()


@router.post("", response_model=RemediationResponse)
def create_remediation(request: RemediationCreateRequest, db: Session = Depends(get_db)) -> RemediationResponse:
    task = create_remediation_task(
        db=db,
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
def submit_remediation_evidence(
    task_id: str,
    request: RemediationEvidenceRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    evidence = add_remediation_evidence(db, task_id=task_id, image_path=request.image_path, note=request.note)
    return {"evidence_id": evidence.id, "task_id": task_id, "status": "submitted"}


@router.post("/{task_id}/verify", response_model=RemediationResponse)
def verify_remediation(
    task_id: str,
    request: RemediationVerifyRequest,
    db: Session = Depends(get_db),
) -> RemediationResponse:
    status = "verified" if request.decision == "accept" else "rejected"
    task = update_remediation_status(db, task_id=task_id, status=status)
    if not task:
        raise HTTPException(status_code=404, detail="remediation task not found")
    return RemediationResponse(
        task_id=task.id,
        analysis_id=task.analysis_id,
        status=task.status,
        title=task.title,
        recommendation=task.recommendation,
    )
