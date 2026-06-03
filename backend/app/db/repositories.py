from datetime import datetime
from time import perf_counter

from sqlalchemy.orm import Session

from app.db.models import (
    AnnotationBatch,
    AnnotationObjectDraft,
    AnnotationSample,
    AnalysisTask,
    Conversation,
    FusedResultRecord,
    HumanReview,
    Message,
    RemediationEvidence,
    RemediationTask,
    TrainingCandidate,
    ToolCall,
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


def latest_fused_result(db: Session, analysis_id: str) -> FusedResultRecord | None:
    return (
        db.query(FusedResultRecord)
        .filter(FusedResultRecord.analysis_id == analysis_id)
        .order_by(FusedResultRecord.created_at.desc())
        .first()
    )


def create_tool_call(
    db: Session,
    conversation_id: str,
    analysis_id: str | None,
    tool_name: str,
    status: str,
    input_json: dict,
    output_json: dict,
    latency_ms: float | None = None,
) -> ToolCall:
    call = ToolCall(
        conversation_id=conversation_id,
        analysis_id=analysis_id,
        tool_name=tool_name,
        status=status,
        input_json=input_json,
        output_json=output_json,
        latency_ms=latency_ms,
    )
    db.add(call)
    db.commit()
    db.refresh(call)
    return call


def timed_tool_call(db: Session, conversation_id: str, analysis_id: str, tool_name: str, input_json: dict, fn):
    started = perf_counter()
    try:
        result = fn()
        output_json = result if isinstance(result, dict) else {"result": str(result)}
        create_tool_call(
            db,
            conversation_id=conversation_id,
            analysis_id=analysis_id,
            tool_name=tool_name,
            status="ok",
            input_json=input_json,
            output_json=output_json,
            latency_ms=(perf_counter() - started) * 1000,
        )
        return result
    except Exception as exc:
        create_tool_call(
            db,
            conversation_id=conversation_id,
            analysis_id=analysis_id,
            tool_name=tool_name,
            status="error",
            input_json=input_json,
            output_json={"error": str(exc)},
            latency_ms=(perf_counter() - started) * 1000,
        )
        raise


def create_human_review(
    db: Session,
    analysis_id: str,
    item_type: str,
    item_index: int,
    decision: str,
    reviewer: str | None,
    revised_json: dict,
    note: str,
) -> HumanReview:
    review = HumanReview(
        analysis_id=analysis_id,
        item_type=item_type,
        item_index=item_index,
        decision=decision,
        reviewer=reviewer,
        revised_json=revised_json,
        note=note,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def create_remediation_task(
    db: Session,
    conversation_id: str | None,
    analysis_id: str,
    hazard_index: int,
    title: str,
    recommendation: str,
    responsible_person: str | None,
    due_at,
    hazard_json: dict,
) -> RemediationTask:
    task = RemediationTask(
        conversation_id=conversation_id,
        analysis_id=analysis_id,
        hazard_index=hazard_index,
        title=title,
        recommendation=recommendation,
        responsible_person=responsible_person,
        due_at=due_at,
        hazard_json=hazard_json,
        status="open",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def add_remediation_evidence(db: Session, task: RemediationTask, image_path: str, note: str) -> RemediationEvidence:
    evidence = RemediationEvidence(remediation_task_id=task.id, image_path=image_path, note=note)
    task.status = "submitted"
    task.updated_at = datetime.utcnow()
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return evidence


def update_remediation_status(db: Session, task_id: str, status: str) -> RemediationTask | None:
    task = db.get(RemediationTask, task_id)
    if not task:
        return None
    task.status = status
    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task


def latest_vlm_result(db: Session, analysis_id: str) -> VLMResult | None:
    return (
        db.query(VLMResult)
        .filter(VLMResult.analysis_id == analysis_id)
        .order_by(VLMResult.created_at.desc())
        .first()
    )


def latest_yolo_result(db: Session, analysis_id: str) -> YOLOResult | None:
    return (
        db.query(YOLOResult)
        .filter(YOLOResult.analysis_id == analysis_id)
        .order_by(YOLOResult.created_at.desc())
        .first()
    )


def create_annotation_batch(db: Session, source: str, note: str = "") -> AnnotationBatch:
    batch = AnnotationBatch(source=source, status="open", note=note)
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


def create_annotation_sample(
    db: Session,
    batch_id: str | None,
    analysis_id: str | None,
    conversation_id: str | None,
    image_path: str,
    source_type: str,
    model_output_json: dict,
    yolo_output_json: dict,
    fused_result_json: dict,
    draft_json: dict,
    review_json: dict,
    note: str,
) -> AnnotationSample:
    sample = AnnotationSample(
        batch_id=batch_id,
        analysis_id=analysis_id,
        conversation_id=conversation_id,
        image_path=image_path,
        status="pending_review",
        source_type=source_type,
        model_output_json=model_output_json,
        yolo_output_json=yolo_output_json,
        fused_result_json=fused_result_json,
        draft_json=draft_json,
        review_json=review_json,
        note=note,
    )
    db.add(sample)
    db.commit()
    db.refresh(sample)
    draft_json = {**draft_json, "sample_id": sample.id}
    review_json = {**review_json, "sample_id": sample.id}
    sample.draft_json = draft_json
    sample.review_json = review_json
    for obj in draft_json.get("objects") or []:
        db.add(
            AnnotationObjectDraft(
                sample_id=sample.id,
                draft_object_index=int(obj.get("draft_object_index", 0)),
                object_json=obj,
                decision="pending",
                revised_json=obj,
            )
        )
    db.commit()
    db.refresh(sample)
    return sample


def update_annotation_review(db: Session, sample: AnnotationSample, review_json: dict) -> AnnotationSample:
    sample.review_json = review_json
    sample.status = "reviewed"
    sample.updated_at = datetime.utcnow()
    for item in review_json.get("objects") or []:
        draft = (
            db.query(AnnotationObjectDraft)
            .filter(
                AnnotationObjectDraft.sample_id == sample.id,
                AnnotationObjectDraft.draft_object_index == item.get("draft_object_index"),
            )
            .first()
        )
        if draft:
            draft.decision = item.get("decision", "pending")
            draft.revised_json = item.get("revised") or {}
    db.commit()
    db.refresh(sample)
    return sample


def commit_annotation_sample(db: Session, sample: AnnotationSample, accepted_record_json: dict, candidate_type: str) -> TrainingCandidate | None:
    sample.accepted_record_json = accepted_record_json
    accepted_count = len(accepted_record_json.get("objects") or [])
    sample.status = "committed" if accepted_count else "reviewed"
    sample.updated_at = datetime.utcnow()
    candidate = None
    if accepted_count:
        candidate = TrainingCandidate(
            sample_id=sample.id,
            analysis_id=sample.analysis_id,
            candidate_type=candidate_type,
            status="ready",
            payload_json=accepted_record_json,
        )
        db.add(candidate)
    db.commit()
    if candidate:
        db.refresh(candidate)
    db.refresh(sample)
    return candidate
