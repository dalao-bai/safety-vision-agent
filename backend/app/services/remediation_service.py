from app.models.schemas import HazardObject


class RemediationService:
    def default_title(self, hazard: HazardObject | dict, index: int) -> str:
        if isinstance(hazard, dict):
            object_name = hazard.get("object_name", "隐患对象")
            hazard_type = hazard.get("hazard_type") or hazard.get("status", "隐患")
        else:
            object_name = hazard.object_name
            hazard_type = hazard.hazard_type or hazard.status
        return f"整改任务 {index + 1}：{object_name} - {hazard_type}"

    def default_recommendation(self, hazard: HazardObject | dict) -> str:
        if isinstance(hazard, dict):
            rule = hazard.get("rule", "")
            hazard_type = hazard.get("hazard_type") or "安全隐患"
        else:
            rule = hazard.rule
            hazard_type = hazard.hazard_type or "安全隐患"
        if rule:
            return f"针对{hazard_type}，请按规则依据落实整改：{rule}"
        return f"针对{hazard_type}，请进行现场复核并补齐防护措施。"
