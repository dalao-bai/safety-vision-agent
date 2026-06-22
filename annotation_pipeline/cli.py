from __future__ import annotations

import argparse
import json
from pathlib import Path

from .review_records import convert_reviews_to_records
from .review_server import run_review_server
from .runner import run_draft


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="API-assisted four-openings/five-edges annotation and review pipeline")
    parser.add_argument("--config", default="数据标注/api_config.json")
    parser.add_argument("--rule-blocks", default="数据标注/知识图谱主文件/four_openings_edges_rule_blocks.json")
    parser.add_argument("--image-dir", default="数据标注/生成图片")
    parser.add_argument("--output-dir", default="数据标注/annotation_pipeline_outputs")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--single-image")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--sleep", type=float, default=0.8)
    parser.add_argument("--workers", type=int, default=1, help="number of concurrent image workers; keep 1 for serial processing")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--mock-from-json", action="store_true", help="use paired image JSON as API-like draft; no API call")
    parser.add_argument("--write-review-index", action="store_true", help="also generate the legacy static review_index/index.html")
    parser.add_argument("--only-needs-rerun", action="store_true", help="only process samples marked needs_rerun in review_decisions")
    parser.add_argument("--commit-reviewed", action="store_true", help="convert accepted/revised review JSON into accepted_records JSONL")
    parser.add_argument("--append-to-db", action="store_true", help="append accepted_records into annotation_db/records after review conversion")
    parser.add_argument("--db-records-dir", default="数据标注/annotation_db/records")
    parser.add_argument("--source-type", default="generated_seed", choices=["real_site", "generated_seed", "web_collected", "unknown"])
    parser.add_argument("--serve-review", action="store_true", help="start a local browser review tool")
    parser.add_argument("--review-host", default="127.0.0.1")
    parser.add_argument("--review-port", type=int, default=8765)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.serve_review:
        return run_review_server(args)
    if args.commit_reviewed:
        summary = convert_reviews_to_records(Path(args.output_dir), args.append_to_db, Path(args.db_records_dir), args.source_type)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    return run_draft(args)
