import json
from pathlib import Path

from app.core.config import get_settings


class RuleRetriever:
    def __init__(self) -> None:
        self.settings = get_settings()

    def retrieve_for_prompt(self, object_id: str | None = None, top_k: int = 5) -> list[dict]:
        path = self.settings.rule_blocks_file_path
        if not path.exists():
            raise FileNotFoundError(f"rule blocks file not found: {path}")

        rules = json.loads(path.read_text(encoding="utf-8"))
        if object_id:
            rules = [rule for rule in rules if rule.get("object_id") == object_id]
        return rules[:top_k]
