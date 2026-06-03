import asyncio

from app.db.repositories import save_analysis_results, update_analysis_status
from app.db.session import SessionLocal
from app.models.schemas import VLMAnalysisResult, YOLODetectionResult
from app.services.evidence_fusion import EvidenceFusionService
from app.services.rule_retriever import RuleRetriever
from app.services.vlm_client import VLMClient
from app.services.yolo_detector import YOLOHelmetDetector
from app.tasks.celery_app import celery_app


@celery_app.task(name="analyze_image_task", bind=True)
def analyze_image_task(
    self,
    analysis_id: str,
    conversation_id: str,
    image_path: str,
    message: str,
    selected_bbox: list[float] | None = None,
) -> dict:
    db = SessionLocal()
    try:
        update_analysis_status(db, analysis_id, "running")

        rules = RuleRetriever().retrieve_for_prompt()
        vlm_result = asyncio.run(
            VLMClient().analyze_image(
                image_path=image_path,
                question=message,
                candidate_rules=rules,
                target_bbox=selected_bbox,
            )
        )
        if not isinstance(vlm_result, VLMAnalysisResult):
            vlm_result = VLMAnalysisResult.model_validate(vlm_result)

        yolo_result = YOLOHelmetDetector().detect(image_path)
        if not isinstance(yolo_result, YOLODetectionResult):
            yolo_result = YOLODetectionResult.model_validate(yolo_result)

        fused = EvidenceFusionService().fuse(vlm_result, yolo_result)
        save_analysis_results(
            db=db,
            analysis_id=analysis_id,
            vlm_json=vlm_result.model_dump(),
            yolo_json=yolo_result.model_dump(),
            fused_json=fused.model_dump(),
        )

        return {
            "analysis_id": analysis_id,
            "conversation_id": conversation_id,
            "summary": fused.summary,
            "fused_result": fused.model_dump(),
        }
    except Exception:
        update_analysis_status(db, analysis_id, "failed")
        raise
    finally:
        db.close()
