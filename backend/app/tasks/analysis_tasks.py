import asyncio

from app.db.repositories import save_analysis_results, timed_tool_call, update_analysis_status
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

        rules = timed_tool_call(
            db,
            conversation_id=conversation_id,
            analysis_id=analysis_id,
            tool_name="rule_retrieval_tool",
            input_json={"top_k": 5},
            fn=lambda: {"rules": RuleRetriever().retrieve_for_prompt()},
        )["rules"]

        vlm_result = timed_tool_call(
            db,
            conversation_id=conversation_id,
            analysis_id=analysis_id,
            tool_name="vlm_hazard_analysis_tool",
            input_json={"image_path": image_path, "question": message, "target_bbox": selected_bbox},
            fn=lambda: asyncio.run(
                VLMClient().analyze_image(
                    image_path=image_path,
                    question=message,
                    candidate_rules=rules,
                    target_bbox=selected_bbox,
                )
            ).model_dump(),
        )
        vlm_result = VLMAnalysisResult.model_validate(vlm_result)

        yolo_result = timed_tool_call(
            db,
            conversation_id=conversation_id,
            analysis_id=analysis_id,
            tool_name="yolo_helmet_detection_tool",
            input_json={"image_path": image_path},
            fn=lambda: YOLOHelmetDetector().detect(image_path).model_dump(),
        )
        yolo_result = YOLODetectionResult.model_validate(yolo_result)

        fused = timed_tool_call(
            db,
            conversation_id=conversation_id,
            analysis_id=analysis_id,
            tool_name="evidence_fusion_tool",
            input_json={"vlm_object_count": len(vlm_result.objects), "yolo_detection_count": len(yolo_result.detections)},
            fn=lambda: EvidenceFusionService().fuse(vlm_result, yolo_result).model_dump(),
        )
        fused_result = EvidenceFusionService().fuse(vlm_result, yolo_result)
        save_analysis_results(
            db=db,
            analysis_id=analysis_id,
            vlm_json=vlm_result.model_dump(),
            yolo_json=yolo_result.model_dump(),
            fused_json=fused,
        )

        return {
            "analysis_id": analysis_id,
            "conversation_id": conversation_id,
            "summary": fused_result.summary,
            "fused_result": fused,
        }
    except Exception:
        update_analysis_status(db, analysis_id, "failed")
        raise
    finally:
        db.close()
