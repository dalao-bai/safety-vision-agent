#!/usr/bin/env python3
"""Generate a synthetic RAG evaluation dataset from JGJ standards documents.

Usage:
    cd backend
    python scripts/gen_eval_dataset.py [--out eval_dataset.json]

Reads every *.md file under the standards root, extracts substantive chunks,
and asks an LLM to generate a question + ground-truth answer for each. The
resulting JSON can be hand-reviewed / pruned before running eval_rag.py.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Allow running from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.retrieval.standards import chunk_markdown

_STANDARDS_ROOT = (
    Path(__file__).resolve().parents[3]
    / "知识图谱主文件"
    / "标准规范文件"
)

_SYSTEM_PROMPT = (
    "你是一个建筑安全标准专家。根据下面提供的标准条文，生成一个问答对，"
    "要求：问题必须能用该条文直接回答，答案简洁（1-3句话）。"
    "只输出 JSON，格式：{\"question\": \"...\", \"answer\": \"...\"}"
)


def _collect_chunks(root: Path, max_chars: int = 800) -> list[dict]:
    chunks = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        md = path.read_text(encoding="utf-8")
        for j, ch in enumerate(chunk_markdown(md, source=rel, max_chars=max_chars)):
            # Skip very short or heading-only chunks
            body = ch["text"].replace(ch["heading"], "").strip()
            if len(body) < 50:
                continue
            chunks.append({**ch, "id": f"{rel}::{j}"})
    return chunks


def _generate_qa(client, model: str, chunk: dict) -> dict | None:
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": chunk["text"][:1500]},
            ],
            temperature=0.3,
            max_tokens=300,
        )
        raw = resp.choices[0].message.content or ""
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw)
        qa = json.loads(raw)
        return {
            "question": qa["question"],
            "ground_truth_answer": qa["answer"],
            "relevant_chunk_ids": [chunk["id"]],
            "source": chunk["source"],
            "heading": chunk["heading"],
        }
    except Exception as exc:
        print(f"  skip {chunk['id']}: {exc}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="eval_dataset.json")
    parser.add_argument("--max-samples", type=int, default=30,
                        help="Max QA pairs to generate (default 30)")
    parser.add_argument("--stride", type=int, default=3,
                        help="Sample every N-th chunk to get diversity (default 3)")
    args = parser.parse_args()

    if not _STANDARDS_ROOT.exists():
        print(f"Standards root not found: {_STANDARDS_ROOT}", file=sys.stderr)
        sys.exit(1)

    settings = get_settings()
    from openai import OpenAI
    client = OpenAI(base_url=settings.openai_api_base_url, api_key=settings.openai_api_key)

    print(f"Collecting chunks from {_STANDARDS_ROOT} ...")
    chunks = _collect_chunks(_STANDARDS_ROOT)
    # Sample every stride-th chunk for diversity
    sampled = chunks[::args.stride][: args.max_samples]
    print(f"Generating {len(sampled)} QA pairs (sampled from {len(chunks)} chunks) ...")

    dataset = []
    for i, chunk in enumerate(sampled):
        print(f"  [{i+1}/{len(sampled)}] {chunk['id'][:60]}")
        qa = _generate_qa(client, settings.agent_model, chunk)
        if qa:
            dataset.append(qa)

    out_path = Path(args.out)
    out_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved {len(dataset)} QA pairs → {out_path}")
    print("Review and prune the file before running eval_rag.py")


if __name__ == "__main__":
    main()
