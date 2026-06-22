from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.persistence.models import Hazard


def _clean(s: object) -> str:
    """Collapse newlines so VLM/user text can't inject markdown structure."""
    return str(s).replace("\r", " ").replace("\n", " ").strip()


def build_markdown_report(
    session_id: int,
    hazards: list[Hazard],
    report_dir: str,
    object_name_for: Callable[[str], str],
    hazard_name_for: Callable[[str | None], str],
    remediation_for: Callable[[str], list[dict[str, str]]],
) -> str:
    out_dir = Path(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# 四口五临边隐患排查报告", "", f"- 会话:{session_id}",
             f"- 生成时间:{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
             f"- 已确认隐患数:{len(hazards)}", ""]
    if not hazards:
        lines.append("未发现已确认隐患。")
    for i, h in enumerate(hazards, 1):
        lines.append(f"## {i}. {_clean(object_name_for(h.object_id))} — {_clean(hazard_name_for(h.hazard_type_id))}")
        lines.append(f"- 状态:{_clean(h.status)}")
        lines.append(f"- 位置 bbox:{h.bbox}")
        lines.append(f"- 视觉证据:{_clean(h.visual_evidence)}")
        lines.append(f"- 规则依据:{_clean(h.rule_basis)}")
        rem = remediation_for(h.object_id)
        if rem:
            lines.append("- 整改建议(基于合格条件):")
            for item in rem:
                cond = _clean(item.get('condition', ''))
                src = f"（{_clean(item['source'])}）" if item.get("source") else ""
                lines.append(f"  - {cond}{src}")
        lines.append("")
    path = out_dir / f"session_{session_id}_report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)
