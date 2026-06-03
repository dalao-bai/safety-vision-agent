from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import (
    AnalysisTask,
    Conversation,
    FusedResultRecord,
    Message,
    UploadedFile,
    VLMResult,
    YOLOResult,
)


def get_or_create_conversation(db: Session, conversation_id: str | None) -> Conversation:
    if conversation_id:
        existing = db.get(Conversation, conversation_id)
        if existing:
            return existing
    conversation = Conversation(id=conversation_id) if conversation_id else Conversation()
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def add_message(db: Session, conversation_id: str, role: str, content: str) -> Message:
    message = Message(conversation_id=conversation_id, role=role, content=content)
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def add_uploaded_file(
    db: Session,
    original_name: str,
    stored_path: str,
    mime_type: str | None,
    conversation_id: str | None = None,
) -> UploadedFile:
    file_record = UploadedFile(
        conversation_id=conversation_id,
        original_name=original_name,
        stored_path=stored_path,
        mime_type=mime_type,
    )
    db.add(file_record)
    db.commit()
    db.refresh(file_record)
    return file_record


def create_analysis_task(db: Session, conversation_id: str, image_path: str, user_message: str) -> AnalysisTask:
    task = AnalysisTask(
        conversation_id=conversation_id,
        image_path=image_path,
        user_message=user_message,
        status="pending",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def attach_celery_task(db: Session, analysis_id: str, celery_task_id: str) -> None:
    task = db.get(AnalysisTask, analysis_id)
    if task:
        task.celery_task_id = celery_task_id
        task.status = "queued"
        task.updated_at = datetime.utcnow()
        db.commit()


def update_analysis_status(db: Session, analysis_id: str, status: str) -> None:
    task = db.get(AnalysisTask, analysis_id)
    if task:
        task.status = status
        task.updated_at = datetime.utcnow()
        db.commit()


def save_analysis_results(db: Session, analysis_id: str, vlm_json: dict, yolo_json: dict, fused_json: dict) -> None:
    db.add(VLMResult(analysis_id=analysis_id, result_json=vlm_json))
    db.add(YOLOResult(analysis_id=analysis_id, result_json=yolo_json))
    db.add(FusedResultRecord(analysis_id=analysis_id, result_json=fused_json))
    update_analysis_status(db, analysis_id, "completed")
    db.commit()
