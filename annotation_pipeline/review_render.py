from __future__ import annotations

import base64
import html
import mimetypes
from pathlib import Path

from .local_deps import ensure_local_deps

ensure_local_deps()

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None
    ImageDraw = None
    ImageFont = None


def draw_review_overlay(image_path: Path, draft: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    if Image is not None and ImageDraw is not None:
        output_path = output_dir / f"{draft['sample_id']}_review.png"
        draw_review_overlay_png(image_path, draft, output_path)
        return output_path
    output_path = output_dir / f"{draft['sample_id']}_review.svg"
    draw_review_overlay_svg(image_path, draft, output_path)
    return output_path


def draw_review_overlay_png(image_path: Path, draft: dict, output_path: Path) -> None:
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
        small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
    except Exception:
        font = None
        small_font = None
    palette = {
        "confirmed_hazard": (230, 40, 40),
        "safe": (40, 160, 80),
        "uncertain": (230, 150, 30),
    }
    for obj in draft.get("objects", []):
        bbox = obj.get("bbox")
        if not bbox:
            continue
        color = palette.get(obj.get("status"), (80, 120, 230))
        x1, y1, x2, y2 = bbox
        for t in range(4):
            draw.rectangle([x1 - t, y1 - t, x2 + t, y2 + t], outline=color)
        label = f"#{obj.get('draft_object_index')} {obj.get('status') or 'unknown'}"
        label_box = draw.textbbox((x1, max(0, y1 - 30)), label, font=font)
        draw.rectangle([label_box[0] - 4, label_box[1] - 3, label_box[2] + 4, label_box[3] + 3], fill=(0, 0, 0))
        draw.text((x1, max(0, y1 - 30)), label, fill=color, font=font)
    banner = f"{draft['sample_id']} | API draft boxes"
    banner_box = draw.textbbox((8, 8), banner, font=small_font)
    draw.rectangle([4, 4, banner_box[2] + 12, banner_box[3] + 10], fill=(0, 0, 0))
    draw.text((8, 8), banner, fill=(255, 255, 255), font=small_font)
    image.save(output_path)


def draw_review_overlay_svg(image_path: Path, draft: dict, output_path: Path) -> None:
    width = draft["width"]
    height = draft["height"]
    mime = mimetypes.guess_type(image_path.name)[0] or "image/png"
    data_url = f"data:{mime};base64,{base64.b64encode(image_path.read_bytes()).decode('ascii')}"
    colors = {"confirmed_hazard": "#e62828", "safe": "#289f50", "uncertain": "#e6961e"}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<image href="{data_url}" x="0" y="0" width="{width}" height="{height}"/>',
        '<rect x="4" y="4" width="360" height="28" fill="black" opacity="0.85"/>',
        f'<text x="10" y="24" fill="white" font-size="18" font-family="Arial">{html.escape(draft["sample_id"])} | API draft boxes</text>',
    ]
    for obj in draft.get("objects", []):
        bbox = obj.get("bbox")
        if not bbox:
            continue
        x1, y1, x2, y2 = bbox
        color = colors.get(obj.get("status"), "#5078e6")
        parts.append(f'<rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" fill="none" stroke="{color}" stroke-width="4"/>')
        parts.append(f'<text x="{x1}" y="{max(24, y1-8)}" fill="{color}" font-size="22" font-family="Arial" font-weight="bold">#{obj.get("draft_object_index")} {html.escape(str(obj.get("status") or "unknown"))}</text>')
    parts.append("</svg>")
    output_path.write_text("\n".join(parts), encoding="utf-8")

