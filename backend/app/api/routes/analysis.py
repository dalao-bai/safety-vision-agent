from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import FusedResultRecord
from app.db.repositories import (
    add_message,
    attach_celery_task,
    create_analysis_task,
    get_or_create_conversation,
)
from app.db.session import get_db
from app.models.schemas import AnalysisRequest, AnalysisResponse, AnalysisResultResponse, FusedResult, TaskStatusResponse
from app.tasks.analysis_tasks import analyze_image_task
from app.tasks.celery_app import celery_app


router = APIRouter()


@router.post("", response_model=AnalysisResponse)
def create_analysis(request: AnalysisRequest, db: Session = Depends(get_db)) -> AnalysisResponse:
    conversation = get_or_create_conversation(db, request.conversation_id)
    add_message(db, conversation.id, "user", request.message)
    analysis = create_analysis_task(db, conversation.id, request.image_path, request.message)

    async_result = analyze_image_task.delay(
        analysis_id=analysis.id,
        conversation_id=conversation.id,
        image_path=request.image_path,
        message=request.message,
        selected_bbox=request.selected_bbox,
    )
    attach_celery_task(db, analysis.id, async_result.id)

    return AnalysisResponse(
        analysis_id=analysis.id,
        conversation_id=conversation.id,
        task_id=async_result.id,
        status="queued",
    )


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
def get_task_status(task_id: str) -> TaskStatusResponse:
    result = AsyncResult(task_id, app=celery_app)
    payload = result.result if isinstance(result.result, dict) else None
    error = str(result.result) if result.failed() else None
    return TaskStatusResponse(
        task_id=task_id,
        status=result.status.lower(),
        result=payload,
        error=error,
    )


@router.get("/{analysis_id}", response_model=AnalysisResultResponse)
def get_analysis_result(analysis_id: str, db: Session = Depends(get_db)) -> AnalysisResultResponse:
    record = (
        db.query(FusedResultRecord)
        .filter(FusedResultRecord.analysis_id == analysis_id)
        .order_by(FusedResultRecord.created_at.desc())
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="analysis result not found")
    return AnalysisResultResponse(
        analysis_id=analysis_id,
        status="completed",
        result=FusedResult.model_validate(record.result_json),
    )
