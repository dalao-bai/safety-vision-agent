from app.core.config import get_settings
from app.models.schemas import YOLODetectionResult


class YOLOHelmetDetector:
    def __init__(self) -> None:
        self.settings = get_settings()

    def detect(self, image_path: str) -> YOLODetectionResult:
        if not self.settings.yolo_helmet_model_path:
            return YOLODetectionResult(
                detections=[],
                summary={
                    "person_count": 0,
                    "helmet_count": 0,
                    "no_helmet_count": 0,
                },
            )

        from ultralytics import YOLO

        model = YOLO(self.settings.yolo_helmet_model_path)
        results = model.predict(
            source=image_path,
            conf=self.settings.yolo_confidence_threshold,
            verbose=False,
        )

        detections = []
        counts: dict[str, int] = {}
        for result in results:
            names = result.names
            for box in result.boxes:
                label = str(names[int(box.cls[0])])
                confidence = float(box.conf[0])
                bbox = [float(value) for value in box.xyxy[0].tolist()]
                detections.append({"label": label, "bbox": bbox, "confidence": confidence})
                counts[label] = counts.get(label, 0) + 1

        return YOLODetectionResult(
            detections=detections,
            summary={
                "person_count": counts.get("person", 0),
                "helmet_count": counts.get("helmet", 0),
                "no_helmet_count": counts.get("no_helmet", 0),
            },
        )
