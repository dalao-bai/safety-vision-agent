import httpx

from app.core.config import get_settings
from app.models.schemas import YOLODetectionResult


class YOLOHelmetDetector:
    def __init__(self) -> None:
        self.settings = get_settings()

    def detect(self, image_path: str) -> YOLODetectionResult:
        if not self.settings.yolo_api_base_url:
            return YOLODetectionResult(
                detections=[],
                summary={
                    "person_count": 0,
                    "helmet_count": 0,
                    "no_helmet_count": 0,
                    "service_configured": 0,
                },
            )

        payload = {
            "image_path": image_path,
            "tasks": ["person", "helmet", "no_helmet"],
            "confidence_threshold": self.settings.yolo_confidence_threshold,
        }
        headers = {}
        if self.settings.yolo_api_key:
            headers["Authorization"] = f"Bearer {self.settings.yolo_api_key}"

        with httpx.Client(timeout=self.settings.yolo_timeout_seconds) as client:
            response = client.post(self.settings.yolo_api_base_url, json=payload, headers=headers)
            response.raise_for_status()
            return YOLODetectionResult.model_validate(response.json())
