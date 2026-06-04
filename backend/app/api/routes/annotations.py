import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.db.repositories import (
    commit_annotation_sample,
    create_annotation_batch,
    create_annotation_sample,
    get_analysis_task,
    get_annotation_sample,
    latest_fused_result,
    latest_vlm_result,
    latest_yolo_result,
    update_annotation_review,
)
from app.models.schemas import (
    AnnotationCommitRequest,
    AnnotationCommitResponse,
    AnnotationFromAnalysisRequest,
    AnnotationReviewUpdateRequest,
    AnnotationSampleResponse,
)
from app.services.annotation_adapter import (
    apply_review_update,
    build_accepted_records,
    build_draft_from_analysis,
    build_review_template,
)


router = APIRouter()


@router.post("/from-analysis", response_model=AnnotationSampleResponse)
def create_from_analysis(request: AnnotationFromAnalysisRequest) -> AnnotationSampleResponse:
    analysis = get_analysis_task(request.analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="analysis task not found")
    fused = latest_fused_result(request.analysis_id)
    if not fused:
        raise HTTPException(status_code=404, detail="fused result not found")

    vlm = latest_vlm_result(request.analysis_id)
    yolo = latest_yolo_result(request.analysis_id)
    batch = create_annotation_batch(source="analysis_review", note=request.reason)
    draft_json = build_draft_from_analysis(
        sample_id="pending",
        image_path=analysis.image_path,
        fused_result=fused.result_json,
        vlm_result=vlm.result_json if vlm else {},
        yolo_result=yolo.result_json if yolo else {},
    )
    review_json = build_review_template(
        sample_id="pending",
        image_path=analysis.image_path,
        draft_json=draft_json,
        reviewer=request.reviewer,
        note=request.note,
    )
    review_json["source_analysis_id"] = request.analysis_id
    sample = create_annotation_sample(
        batch_id=batch.id,
        analysis_id=request.analysis_id,
        conversation_id=analysis.conversation_id,
        image_path=analysis.image_path,
        source_type="analysis_review",
        model_output_json=vlm.result_json if vlm else {},
        yolo_output_json=yolo.result_json if yolo else {},
        fused_result_json=fused.result_json,
        draft_json=draft_json,
        review_json=review_json,
        note=request.note,
    )
    return sample_response(sample)


@router.get("/samples/{sample_id}", response_model=AnnotationSampleResponse)
def get_sample(sample_id: str) -> AnnotationSampleResponse:
    sample = get_annotation_sample(sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="annotation sample not found")
    return sample_response(sample)


@router.patch("/samples/{sample_id}/review", response_model=AnnotationSampleResponse)
def save_review(sample_id: str, request: AnnotationReviewUpdateRequest) -> AnnotationSampleResponse:
    sample = get_annotation_sample(sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="annotation sample not found")
    review_json = apply_review_update(
        current_review=sample.review_json,
        reviewer=request.reviewer,
        image_decision=request.image_decision,
        review_status=request.review_status,
        objects=[item.model_dump() for item in request.objects],
        note=request.note,
    )
    updated = update_annotation_review(sample_id, review_json)
    return sample_response(updated)


@router.post("/samples/{sample_id}/commit", response_model=AnnotationCommitResponse)
def commit_sample(sample_id: str, request: AnnotationCommitRequest) -> AnnotationCommitResponse:
    if request.append_to_db:
        raise HTTPException(status_code=400, detail="append_to_db is not supported by the Agent API yet; use generated accepted_records for manual export")
    sample = get_annotation_sample(sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="annotation sample not found")
    accepted = build_accepted_records(sample.id, sample.image_path, sample.review_json, sample.draft_json)
    if accepted.get("errors"):
        raise HTTPException(status_code=400, detail={"message": "accepted records validation failed", "errors": accepted["errors"]})
    write_accepted_records(sample.id, accepted)
    candidate = commit_annotation_sample(sample.id, accepted, request.candidate_type)
    updated = get_annotation_sample(sample.id)
    return AnnotationCommitResponse(
        sample_id=sample.id,
        status=updated.status if updated else sample.status,
        accepted_images=len(accepted.get("images") or []),
        accepted_objects=len(accepted.get("objects") or []),
        training_candidate_id=candidate.id if candidate else None,
        accepted_record_json=accepted,
    )


def write_accepted_records(sample_id: str, accepted: dict) -> None:
    output_dir = get_settings().output_path / "annotation_feedback" / sample_id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "accepted_records.json").write_text(json.dumps(accepted, ensure_ascii=False, indent=2), encoding="utf-8")
    write_jsonl(output_dir / "images.jsonl", accepted.get("images") or [])
    write_jsonl(output_dir / "objects.jsonl", accepted.get("objects") or [])


def write_jsonl(path: Path, records: list[dict]) -> None:
    text = "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def sample_response(sample) -> AnnotationSampleResponse:
    return AnnotationSampleResponse(
        sample_id=sample.id,
        batch_id=sample.batch_id,
        analysis_id=sample.analysis_id,
        image_path=sample.image_path,
        status=sample.status,
        draft_json=sample.draft_json,
        review_json=sample.review_json,
        accepted_record_json=sample.accepted_record_json,
        created_at=sample.created_at,
    )
