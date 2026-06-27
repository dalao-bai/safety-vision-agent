"""Unit tests for RAG evaluation metric functions in scripts/eval_rag.py."""
import math
import sys
from pathlib import Path

# Make scripts importable without installing
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from eval_rag import (
    context_precision,
    context_recall,
    ndcg_at_k,
    reciprocal_rank,
)


# ---------------------------------------------------------------------------
# context_recall
# ---------------------------------------------------------------------------

def test_context_recall_perfect():
    relevant = {"a", "b"}
    retrieved = ["a", "b", "c"]
    assert context_recall(relevant, retrieved) == 1.0


def test_context_recall_partial():
    relevant = {"a", "b", "c"}
    retrieved = ["a", "b", "x"]
    result = context_recall(relevant, retrieved)
    assert abs(result - 2 / 3) < 1e-9


def test_context_recall_zero():
    assert context_recall({"a", "b"}, ["x", "y"]) == 0.0


def test_context_recall_empty_relevant():
    # No annotated relevant chunks → vacuously perfect recall
    assert context_recall(set(), ["x", "y"]) == 1.0


# ---------------------------------------------------------------------------
# context_precision
# ---------------------------------------------------------------------------

def test_context_precision_perfect():
    assert context_precision({"a", "b"}, ["a", "b"]) == 1.0


def test_context_precision_partial():
    relevant = {"a"}
    retrieved = ["a", "b", "c"]
    result = context_precision(relevant, retrieved)
    assert abs(result - 1 / 3) < 1e-9


def test_context_precision_zero():
    assert context_precision({"a"}, ["x", "y"]) == 0.0


def test_context_precision_empty_retrieved():
    assert context_precision({"a"}, []) == 0.0


# ---------------------------------------------------------------------------
# MRR (reciprocal rank)
# ---------------------------------------------------------------------------

def test_mrr_first_is_relevant():
    assert reciprocal_rank({"a"}, ["a", "b", "c"]) == 1.0


def test_mrr_second_is_relevant():
    result = reciprocal_rank({"b"}, ["a", "b", "c"])
    assert abs(result - 0.5) < 1e-9


def test_mrr_third_is_relevant():
    result = reciprocal_rank({"c"}, ["a", "b", "c"])
    assert abs(result - 1 / 3) < 1e-9


def test_mrr_none_relevant():
    assert reciprocal_rank({"z"}, ["a", "b", "c"]) == 0.0


def test_mrr_empty_retrieved():
    assert reciprocal_rank({"a"}, []) == 0.0


# ---------------------------------------------------------------------------
# NDCG@k
# ---------------------------------------------------------------------------

def test_ndcg_perfect():
    # All relevant items at the top → NDCG = 1.0
    result = ndcg_at_k({"a", "b"}, ["a", "b", "c"], k=3)
    assert abs(result - 1.0) < 1e-9


def test_ndcg_ideal_ranking():
    # Single relevant item at position 1 → ideal DCG = actual DCG
    result = ndcg_at_k({"a"}, ["a", "b", "c"], k=3)
    assert abs(result - 1.0) < 1e-9


def test_ndcg_relevant_second():
    # Relevant item at position 2: DCG = 1/log2(3); ideal = 1/log2(2)
    result = ndcg_at_k({"b"}, ["a", "b", "c"], k=3)
    expected = (1.0 / math.log2(3)) / (1.0 / math.log2(2))
    assert abs(result - expected) < 1e-9


def test_ndcg_no_relevant():
    assert ndcg_at_k({"z"}, ["a", "b", "c"], k=3) == 0.0


def test_ndcg_k_limits_window():
    # Only look at first k=1; relevant item is at position 2 → 0.0
    assert ndcg_at_k({"b"}, ["a", "b", "c"], k=1) == 0.0


def test_ndcg_empty_retrieved():
    assert ndcg_at_k({"a"}, [], k=3) == 0.0
