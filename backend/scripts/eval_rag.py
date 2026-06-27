#!/usr/bin/env python3
"""Offline RAG evaluation script.

Computes retrieval-layer metrics (no LLM needed):
  - Context Recall     — of all annotated relevant chunks, how many were retrieved
  - Context Precision  — of retrieved chunks, what fraction is annotated relevant
  - MRR               — mean reciprocal rank of first relevant result
  - NDCG@k            — normalized discounted cumulative gain

And generation-layer metrics (requires LLM + RAGAS):
  - Faithfulness       — fraction of answer claims supported by context
  - Answer Relevancy   — how well the answer addresses the question

Usage:
    cd backend
    python scripts/eval_rag.py [--dataset eval_dataset.json] [--no-rerank] [--no-gen]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.retrieval.standards import StandardsIndex, openai_embedder

_STANDARDS_ROOT = (
    Path(__file__).resolve().parents[3]
    / "知识图谱主文件"
    / "标准规范文件"
)


# ---------------------------------------------------------------------------
# Retrieval metrics (pure Python, no LLM)
# ---------------------------------------------------------------------------

def context_recall(relevant_ids: set[str], retrieved_ids: list[str]) -> float:
    if not relevant_ids:
        return 1.0
    hit = sum(1 for r in retrieved_ids if r in relevant_ids)
    return hit / len(relevant_ids)


def context_precision(relevant_ids: set[str], retrieved_ids: list[str]) -> float:
    if not retrieved_ids:
        return 0.0
    hit = sum(1 for r in retrieved_ids if r in relevant_ids)
    return hit / len(retrieved_ids)


def reciprocal_rank(relevant_ids: set[str], retrieved_ids: list[str]) -> float:
    for i, rid in enumerate(retrieved_ids):
        if rid in relevant_ids:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(relevant_ids: set[str], retrieved_ids: list[str], k: int) -> float:
    def dcg(ids):
        return sum(
            (1.0 if rid in relevant_ids else 0.0) / math.log2(i + 2)
            for i, rid in enumerate(ids[:k])
        )
    actual = dcg(retrieved_ids)
    ideal_list = list(relevant_ids) + [x for x in retrieved_ids if x not in relevant_ids]
    ideal = dcg(ideal_list)
    return actual / ideal if ideal > 0 else 0.0


def _chunk_ids_for_hits(hits: list[dict], index: "StandardsIndex") -> list[str]:
    """Extract chunk IDs directly from hit dicts (populated by search())."""
    return [h.get("id", f"unknown::{i}") for i, h in enumerate(hits)]


# ---------------------------------------------------------------------------
# Generation metrics via RAGAS
# ---------------------------------------------------------------------------

def _ragas_score(question: str, answer: str, contexts: list[str], settings) -> dict:
    try:
        from ragas import evaluate
        from ragas.metrics import faithfulness, answer_relevancy
        from datasets import Dataset
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings

        llm = ChatOpenAI(
            base_url=settings.openai_api_base_url,
            api_key=settings.openai_api_key,
            model=settings.agent_model,
            temperature=0,
        )
        embeddings = OpenAIEmbeddings(
            base_url=settings.embedding_api_base_url or settings.openai_api_base_url,
            api_key=settings.embedding_api_key or settings.openai_api_key,
            model=settings.embedding_model,
        )
        ds = Dataset.from_dict({
            "question": [question],
            "answer": [answer],
            "contexts": [contexts],
        })
        result = evaluate(
            ds,
            metrics=[faithfulness, answer_relevancy],
            llm=llm,
            embeddings=embeddings,
        )
        df = result.to_pandas()
        row = df.iloc[0]
        return {
            "faithfulness": float(row.get("faithfulness", float("nan"))),
            "answer_relevancy": float(row.get("answer_relevancy", float("nan"))),
        }
    except Exception as exc:
        print(f"    RAGAS error: {exc}", file=sys.stderr)
        return {"faithfulness": float("nan"), "answer_relevancy": float("nan")}


def _generate_answer(client, model: str, question: str, contexts: list[str]) -> str:
    ctx_text = "\n\n".join(f"[{i+1}] {c}" for i, c in enumerate(contexts))
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": (
                "你是建筑安全专家。根据以下标准条文回答问题，答案简洁准确。\n\n"
                f"参考条文：\n{ctx_text}"
            )},
            {"role": "user", "content": question},
        ],
        temperature=0,
        max_tokens=300,
    )
    return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="eval_dataset.json")
    parser.add_argument("--no-rerank", action="store_true",
                        help="Disable cross-encoder reranking (baseline comparison)")
    parser.add_argument("--no-gen", action="store_true",
                        help="Skip generation-layer metrics (faster, no LLM calls)")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--out", default="metrics.json")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"Dataset not found: {dataset_path}", file=sys.stderr)
        print("Run scripts/gen_eval_dataset.py first.", file=sys.stderr)
        sys.exit(1)

    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    print(f"Loaded {len(dataset)} eval samples from {dataset_path}")

    settings = get_settings()
    embedder = openai_embedder(settings)

    index = StandardsIndex(
        persist_dir=settings.chroma_dir,
        embedder=embedder,
        max_chars=settings.chunk_max_chars,
        overlap_chars=settings.chunk_overlap_chars,
        top_k_dense=settings.retrieval_top_k_dense,
        top_k_bm25=settings.retrieval_top_k_bm25,
        rrf_k=settings.retrieval_rrf_k,
        final_k=settings.retrieval_final_k,
        reranker_model=settings.reranker_model,
        reranker_enabled=not args.no_rerank,
    )

    col = index._collection()
    if col is None or col.count() == 0:
        print("Index is empty — run scripts/build_standards_index.py first.", file=sys.stderr)
        sys.exit(1)

    from openai import OpenAI
    client = OpenAI(base_url=settings.openai_api_base_url, api_key=settings.openai_api_key)

    records = []
    for i, sample in enumerate(dataset):
        question = sample["question"]
        relevant_ids = set(sample.get("relevant_chunk_ids", []))
        print(f"[{i+1}/{len(dataset)}] {question[:60]}")

        hits = index.search(question, top_k=args.top_k)
        retrieved_ids = _chunk_ids_for_hits(hits, index)
        contexts = [h["text"] for h in hits]

        recall = context_recall(relevant_ids, retrieved_ids)
        precision = context_precision(relevant_ids, retrieved_ids)
        rr = reciprocal_rank(relevant_ids, retrieved_ids)
        ndcg = ndcg_at_k(relevant_ids, retrieved_ids, k=args.top_k)

        rec: dict = {
            "question": question,
            "context_recall": recall,
            "context_precision": precision,
            "mrr": rr,
            f"ndcg@{args.top_k}": ndcg,
        }

        if not args.no_gen:
            answer = _generate_answer(client, settings.agent_model, question, contexts)
            gen_scores = _ragas_score(question, answer, contexts, settings)
            rec["generated_answer"] = answer
            rec.update(gen_scores)

        records.append(rec)
        print(f"  recall={recall:.3f}  precision={precision:.3f}  "
              f"mrr={rr:.3f}  ndcg={ndcg:.3f}"
              + (f"  faithful={rec.get('faithfulness', float('nan')):.3f}"
                 f"  relevancy={rec.get('answer_relevancy', float('nan')):.3f}"
                 if not args.no_gen else ""))

    # Aggregate
    def _mean(key):
        vals = [r[key] for r in records if not math.isnan(r.get(key, float("nan")))]
        return sum(vals) / len(vals) if vals else float("nan")

    summary = {
        "n_samples": len(records),
        "rerank_enabled": not args.no_rerank,
        "top_k": args.top_k,
        "mean_context_recall": _mean("context_recall"),
        "mean_context_precision": _mean("context_precision"),
        "mean_mrr": _mean("mrr"),
        f"mean_ndcg@{args.top_k}": _mean(f"ndcg@{args.top_k}"),
    }
    if not args.no_gen:
        summary["mean_faithfulness"] = _mean("faithfulness")
        summary["mean_answer_relevancy"] = _mean("answer_relevancy")

    output = {"summary": summary, "details": records}
    Path(args.out).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== Summary ===")
    for k, v in summary.items():
        if isinstance(v, float):
            print(f"  {k}: {v:.4f}")
        else:
            print(f"  {k}: {v}")
    print(f"\nFull results → {args.out}")


if __name__ == "__main__":
    main()
