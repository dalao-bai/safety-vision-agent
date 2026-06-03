import httpx

from app.core.config import get_settings
from app.models.schemas import VLMAnalysisResult


class VLMClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def analyze_image(
        self,
        image_path: str,
        question: str,
        candidate_rules: list[dict],
        target_bbox: list[float] | None = None,
    ) -> VLMAnalysisResult:
        if not self.settings.vlm_api_base_url:
            return VLMAnalysisResult(
                objects=[],
                summary="VLM API 尚未配置。请在 .env 中填写 VLM_API_BASE_URL、VLM_API_KEY 和 VLM_MODEL_NAME。",
            )

        payload = {
            "image_path": image_path,
            "question": question,
            "candidate_rules": candidate_rules,
            "target_bbox": target_bbox,
            "context": {"scene": "four_openings_edges"},
        }
        headers = {}
        if self.settings.vlm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.vlm_api_key}"

        async with httpx.AsyncClient(timeout=self.settings.vlm_timeout_seconds) as client:
            response = await client.post(self.settings.vlm_api_base_url, json=payload, headers=headers)
            response.raise_for_status()
            return VLMAnalysisResult.model_validate(response.json())
