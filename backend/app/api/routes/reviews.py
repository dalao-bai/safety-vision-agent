from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.repositories import create_human_review
from app.db.session import get_db
from app.models.schemas import ReviewCreateRequest, ReviewResponse


router = APIRouter()


@router.post("", response_model=ReviewResponse)
def create_review(request: ReviewCreateRequest, db: Session = Depends(get_db)) -> ReviewResponse:
    review = create_human_review(
        db=db,
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
