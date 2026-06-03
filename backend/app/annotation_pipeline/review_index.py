from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any


def review_template(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_id": draft["sample_id"],
        "image_path": draft["image_path"],
        "review_status": "pending",
        "image_decision": "pending",
        "objects": [
            {
                "draft_object_index": obj["draft_object_index"],
                "decision": "pending",
                "revised": None,
                "review_note": "",
            }
            for obj in draft.get("objects", [])
        ],
        "review_note": "",
    }


def rel_link(target: Path, base_dir: Path) -> str:
    try:
        return Path(os.path.relpath(target.resolve(), base_dir.resolve())).as_posix()
    except Exception:
        return target.as_posix()


def generate_review_index(drafts: list[dict[str, Any]], overlay_paths: dict[str, Path], output_dir: Path, review_dir: Path) -> Path:
    index_dir = output_dir / "review_index"
    index_dir.mkdir(parents=True, exist_ok=True)
    parts = [
        "<!doctype html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>四口五临边 API 草标复盘</title>",
        "<style>",
        "body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:0;background:#f6f7f9;color:#172033;}",
        "header{position:sticky;top:0;background:#fff;border-bottom:1px solid #d8dde6;padding:14px 24px;z-index:2;}",
        "main{max-width:1280px;margin:0 auto;padding:20px;}",
        "section{background:#fff;border:1px solid #d8dde6;border-radius:8px;margin:0 0 18px;padding:16px;}",
        ".meta{display:flex;gap:16px;flex-wrap:wrap;color:#5d6678;font-size:14px;}",
        ".imgs{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:12px 0;}",
        ".imgs img{width:100%;height:auto;border:1px solid #d8dde6;border-radius:6px;background:#eee;}",
        "table{width:100%;border-collapse:collapse;font-size:14px;}",
        "th,td{border-top:1px solid #e3e7ee;text-align:left;vertical-align:top;padding:8px;}",
        "th{background:#f1f3f6;color:#303849;}",
        "code{background:#eef1f5;padding:2px 4px;border-radius:4px;}",
        ".rule{max-width:520px;white-space:pre-wrap;}",
        ".warn{color:#a85b00;}",
        "@media(max-width:900px){.imgs{grid-template-columns:1fr;}}",
        "</style>",
        "</head>",
        "<body>",
        "<header><strong>四口五临边 API 草标复盘</strong><div class='meta'>HTML 只用于查看；人工修改对应的 review JSON。</div></header>",
        "<main>",
    ]
    for draft in drafts:
        sample_id = draft["sample_id"]
        image_path = Path(draft["image_path"])
        overlay_path = overlay_paths.get(sample_id)
        review_path = review_dir / f"{sample_id}.review.json"
        parts.extend([
            "<section>",
            f"<h2>{html.escape(sample_id)}</h2>",
            "<div class='meta'>",
            f"<span>image: <code>{html.escape(draft['image_path'])}</code></span>",
            f"<span>size: {draft['width']}x{draft['height']}</span>",
            f"<span>review JSON: <code>{html.escape(review_path.as_posix())}</code></span>",
            "</div>",
            "<div class='imgs'>",
            f"<div><div>原图</div><img src='{html.escape(rel_link(image_path, index_dir))}'></div>",
            f"<div><div>草标框</div><img src='{html.escape(rel_link(overlay_path, index_dir)) if overlay_path else ''}'></div>",
            "</div>",
        ])
        if draft.get("objects"):
            parts.append("<table><thead><tr><th>#</th><th>对象</th><th>bbox</th><th>状态</th><th>证据</th><th>缺失证据</th><th>规则</th><th>警告</th></tr></thead><tbody>")
            for obj in draft["objects"]:
                parts.append(
                    "<tr>"
                    f"<td>{obj.get('draft_object_index')}</td>"
                    f"<td>{html.escape(str(obj.get('object_name') or ''))}<br><code>{html.escape(str(obj.get('object_id') or ''))}</code></td>"
                    f"<td><code>{html.escape(json.dumps(obj.get('bbox'), ensure_ascii=False))}</code></td>"
                    f"<td>{html.escape(str(obj.get('status') or ''))}<br>{html.escape(str(obj.get('hazard_type') or ''))}<br>{html.escape(str(obj.get('uncertainty_reason') or ''))}</td>"
                    f"<td>{html.escape(str(obj.get('visual_evidence') or ''))}</td>"
                    f"<td>{html.escape(str(obj.get('missing_evidence') or ''))}</td>"
                    f"<td class='rule'><code>{html.escape(str(obj.get('rule_id') or ''))}</code><br>{html.escape(str(obj.get('rule') or ''))}</td>"
                    f"<td class='warn'>{html.escape(', '.join(obj.get('validation_warnings') or []))}</td>"
                    "</tr>"
                )
            parts.append("</tbody></table>")
        else:
            parts.append("<p>该图片没有 API 草标对象，请人工确认是否确实没有四口五临边对象。</p>")
        parts.append("</section>")
    parts.extend(["</main>", "</body>", "</html>"])
    index_path = index_dir / "index.html"
    index_path.write_text("\n".join(parts), encoding="utf-8")
    return index_path
