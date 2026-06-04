from fastapi import APIRouter, HTTPException

from app.db.repositories import create_human_review, latest_fused_result
from app.models.schemas import FusedResult, ReviewCreateRequest, ReviewResponse


router = APIRouter()


def _validate_review_target(request: ReviewCreateRequest) -> None:
    record = latest_fused_result(request.analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="analysis result not found")

    fused = FusedResult.model_validate(record.result_json)
    collections = {
        "hazard": fused.hazards,
        "uncertain": fused.uncertain_items,
        "detection": fused.detections,
    }
    items = collections.get(request.item_type)
    if items is None:
        raise HTTPException(status_code=400, detail="unsupported review item_type")
    if request.item_index < 0 or request.item_index >= len(items):
        raise HTTPException(status_code=400, detail="review item_index out of range")


@router.post("", response_model=ReviewResponse)
def create_review(request: ReviewCreateRequest) -> ReviewResponse:
    _validate_review_target(request)
    review = create_human_review(
        analysis_id=request.analysis_id,
        item_type=request.item_type,
        item_index=request.item_index,
        decision=request.decision,
        reviewer=request.reviewer,
        revised_json=request.revised_json,
        note=request.note,
    )
    return ReviewResponse(
        review_id=review.id,
        analysis_id=review.analysis_id,
        decision=review.decision,
        note=review.note,
    )
