from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .api_client import call_api, extract_response_text, parse_json_text
from .image_utils import find_images, image_dimensions, stable_sample_id
from .io_utils import load_config, load_json, responses_endpoint, write_json
from .normalize import normalize_draft
from .prompt import build_prompt
from .review_index import generate_review_index, review_template
from .review_render import draw_review_overlay
from .rules import RuleStore
from .summary import draft_summary


def process_image_draft(
    index: int,
    total: int,
    image_path: Path,
    args: argparse.Namespace,
    rules: RuleStore,
    endpoint: str,
    api_key: str,
    model: str,
    raw_dir: Path,
    draft_dir: Path,
    boxed_dir: Path,
    review_dir: Path,
    error_dir: Path,
) -> dict[str, Any]:
    sample_id = stable_sample_id(image_path)
    draft_path = draft_dir / f"{sample_id}.json"
    try:
        if draft_path.exists() and not args.overwrite:
            draft = load_json(draft_path)
            overlay_path = draw_review_overlay(image_path, draft, boxed_dir)
            return {"ok": True, "index": index, "total": total, "image_path": image_path, "sample_id": sample_id, "draft": draft, "overlay_path": overlay_path}

        width, height = image_dimensions(image_path)
        if args.mock_from_json:
            paired_json = image_path.with_suffix(".json")
            parsed = load_json(paired_json) if paired_json.exists() else {"sample_id": image_path.stem, "image_path": image_path.as_posix(), "objects": []}
            raw = {"mock": True, "source_json": paired_json.as_posix() if paired_json.exists() else None}
        else:
            prompt = build_prompt(image_path, width, height, rules)
            raw = call_api(endpoint, api_key, model, prompt, image_path, args.timeout)
            parsed = parse_json_text(extract_response_text(raw))

        draft = normalize_draft(parsed, image_path, width, height, rules, model, args.mock_from_json)
        write_json(raw_dir / f"{sample_id}.raw.json", raw)
        write_json(draft_path, draft)
        review_path = review_dir / f"{sample_id}.review.json"
        if args.overwrite or not review_path.exists():
            previous_review = load_json(review_path) if review_path.exists() else {}
            review = review_template(draft)
            if getattr(args, "only_needs_rerun", False):
                mark_rerun_completed(review, previous_review)
            write_json(review_path, review)
        overlay_path = draw_review_overlay(image_path, draft, boxed_dir)
        return {"ok": True, "index": index, "total": total, "image_path": image_path, "sample_id": sample_id, "draft": draft, "overlay_path": overlay_path}
    except Exception as exc:
        (error_dir / f"{sample_id}.txt").write_text(str(exc), encoding="utf-8")
        return {"ok": False, "index": index, "total": total, "image_path": image_path, "sample_id": sample_id, "error": str(exc)}


def run_draft(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    raw_dir = output_dir / "raw_response"
    draft_dir = output_dir / "draft_json"
    boxed_dir = output_dir / "boxed_review"
    review_dir = output_dir / "review_decisions"
    error_dir = output_dir / "errors"
    directories = [raw_dir, draft_dir, boxed_dir, review_dir, error_dir]
    if args.write_review_index:
        directories.append(output_dir / "review_index")
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

    rules = RuleStore.load(Path(args.rule_blocks))
    endpoint = api_key = model = ""
    if args.mock_from_json:
        model = args.model or "mock-from-json"
    else:
        config = load_config(Path(args.config))
        endpoint = responses_endpoint(config["api_endpoint"])
        api_key = config["api_key"]
        model = args.model or config["model"]

    images = find_images(Path(args.image_dir), args.single_image)
    if args.limit:
        images = images[: args.limit]
    rerun_ids: set[str] = set()
    if args.only_needs_rerun:
        rerun_ids = load_needs_rerun_ids(review_dir)
        images = [image_path for image_path in images if stable_sample_id(image_path) in rerun_ids]
        args.overwrite = True
    workers = max(1, int(args.workers))
    print(f"images={len(images)} model={model} output_dir={output_dir} workers={workers}")
    if args.only_needs_rerun:
        print(f"needs_rerun_marked={len(rerun_ids)} matched_images={len(images)} overwrite=True", flush=True)

    drafts: list[dict[str, Any]] = []
    overlay_paths: dict[str, Path] = {}
    error_count = 0

    if workers == 1:
        for index, image_path in enumerate(images, 1):
            print(f"[{index}/{len(images)}] {image_path}", flush=True)
            result = process_image_draft(index, len(images), image_path, args, rules, endpoint, api_key, model, raw_dir, draft_dir, boxed_dir, review_dir, error_dir)
            if result["ok"]:
                drafts.append(result["draft"])
                overlay_paths[result["sample_id"]] = result["overlay_path"]
            else:
                error_count += 1
                print(f"  ERROR: {result['error']}", file=sys.stderr, flush=True)
            if not args.mock_from_json:
                time.sleep(args.sleep)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(process_image_draft, index, len(images), image_path, args, rules, endpoint, api_key, model, raw_dir, draft_dir, boxed_dir, review_dir, error_dir)
                for index, image_path in enumerate(images, 1)
            ]
            for future in as_completed(futures):
                result = future.result()
                if result["ok"]:
                    drafts.append(result["draft"])
                    overlay_paths[result["sample_id"]] = result["overlay_path"]
                    print(f"[{result['index']}/{result['total']}] OK {result['image_path']}", flush=True)
                else:
                    error_count += 1
                    print(f"[{result['index']}/{result['total']}] ERROR {result['image_path']}: {result['error']}", file=sys.stderr, flush=True)

    drafts.sort(key=lambda item: item["sample_id"])
    summary = draft_summary(drafts, error_count)
    if args.write_review_index:
        index_path = generate_review_index(drafts, overlay_paths, output_dir, review_dir)
        summary["review_index"] = index_path.as_posix()
    else:
        summary["review_index"] = None
        summary["review_tool"] = f"python3 api_annotation_pipeline.py --serve-review --output-dir {output_dir.as_posix()}"
    write_json(output_dir / "draft_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def load_needs_rerun_ids(review_dir: Path) -> set[str]:
    sample_ids: set[str] = set()
    for review_path in sorted(review_dir.glob("*.review.json")):
        try:
            review = load_json(review_path)
        except Exception:
            continue
        if review.get("needs_rerun") is True:
            sample_id = review.get("sample_id") or review_path.stem.replace(".review", "")
            sample_ids.add(str(sample_id))
    return sample_ids


def mark_rerun_completed(review: dict[str, Any], previous_review: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    history = previous_review.get("rerun_history")
    if not isinstance(history, list):
        history = []
    previous_count = previous_review.get("rerun_count")
    if not isinstance(previous_count, int):
        previous_count = len(history)
    history.append(
        {
            "completed_at": now,
            "reason": previous_review.get("rerun_note") or "",
        }
    )
    review["needs_rerun"] = False
    review["rerun_status"] = "completed"
    review["last_rerun_at"] = now
    review["rerun_count"] = previous_count + 1
    review["rerun_history"] = history
