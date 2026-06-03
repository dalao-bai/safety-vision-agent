from app.models.schemas import HazardObject, UncertaintyFollowUp


class UncertaintyResolver:
    def build_followups(self, uncertain_items: list[HazardObject]) -> list[UncertaintyFollowUp]:
        return [self._build_followup(item) for item in uncertain_items]

    def _build_followup(self, item: HazardObject) -> UncertaintyFollowUp:
        reason = item.uncertainty_reason or "visual_rule_evidence_insufficient"
        missing = item.missing_evidence or "当前图像证据不足，无法形成确定判断。"

        if reason == "protective_component_not_visible":
            question = f"{item.object_name} 的关键防护构件不可见，能否补充无遮挡近景图？"
            suggestion = "请从正面和侧面各补拍一张，尽量避开材料遮挡，覆盖洞口或临边完整防护构件。"
        elif reason == "external_context_required":
            question = f"{item.object_name} 的判断依赖现场工程阶段或验收资料，能否补充现场背景信息？"
            suggestion = "请补充工程阶段、验收记录、坠落半径或现场复核资料，必要时上传全景图。"
        else:
            question = f"{item.object_name} 的图像证据不足，能否补充更清晰的局部图片？"
            suggestion = "请补拍近景图，确保能看清防护连续性、固定状态、构件连接和周边尺度关系。"

        return UncertaintyFollowUp(
            object_name=item.object_name,
            bbox=item.bbox,
            uncertainty_reason=reason,
            missing_evidence=missing,
            follow_up_question=question,
            capture_suggestion=suggestion,
        )
