from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

import chromadb

Embedder = Callable[[list[str]], list[list[float]]]

_COLLECTION = "standards"


def chunk_markdown(
    md: str,
    source: str,
    max_chars: int = 800,
    overlap_chars: int = 100,
) -> list[dict[str, str]]:
    """Split markdown into chunks at headings; further split oversized sections.

    Each heading section is kept whole if <= max_chars. Longer sections are
    slid into overlapping sub-chunks so no chunk exceeds max_chars.
    """
    parts = re.split(r"(?m)^(#{1,6}\s.*)$", md)
    raw_sections: list[dict[str, str]] = []
    pre = parts[0].strip()
    if pre:
        raw_sections.append({"text": pre, "source": source, "heading": ""})
    for i in range(1, len(parts), 2):
        heading = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        text = (heading + "\n" + body).strip()
        if text:
            raw_sections.append({"text": text, "source": source, "heading": heading})

    chunks: list[dict[str, str]] = []
    for sec in raw_sections:
        text = sec["text"]
        if len(text) <= max_chars:
            chunks.append(sec)
        else:
            # Sliding window: step = max_chars - overlap_chars
            step = max(1, max_chars - overlap_chars)
            idx = 0
            chunk_i = 0
            while idx < len(text):
                sub = text[idx: idx + max_chars]
                chunks.append({
                    "text": sub,
                    "source": sec["source"],
                    "heading": sec["heading"],
                    "chunk_index": chunk_i,
                })
                idx += step
                chunk_i += 1
    return chunks


class StandardsIndex:
    """施工规范的混合检索索引（向量+BM25+重排）。"""

    def __init__(self, persist_dir: str, embedder: Embedder,
                 max_chars: int = 800, overlap_chars: int = 100,
                 top_k_dense: int = 20, top_k_bm25: int = 20,
                 rrf_k: int = 60, final_k: int = 5,
                 reranker_model: str = "BAAI/bge-reranker-base",
                 reranker_enabled: bool = True):
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._embedder = embedder
        self._max_chars = max_chars
        self._overlap_chars = overlap_chars
        self._top_k_dense = top_k_dense
        self._top_k_bm25 = top_k_bm25
        self._rrf_k = rrf_k
        self._final_k = final_k
        self._reranker_model = reranker_model
        self._reranker_enabled = reranker_enabled

        self._bm25 = None
        self._bm25_docs: list[dict] = []
        self._reranker = None

    def _collection(self):
        try:
            return self._client.get_collection(_COLLECTION)
        except Exception:
            return None

    def build(self, roots: list[Path]) -> int:
        try:
            self._client.delete_collection(_COLLECTION)
        except Exception:
            pass
        col = self._client.create_collection(_COLLECTION)
        docs, metas, ids = [], [], []
        for root in roots:
            for path in sorted(root.rglob("*.md")):
                rel = path.relative_to(root).as_posix()
                md = path.read_text(encoding="utf-8")
                for j, ch in enumerate(chunk_markdown(
                    md, source=rel,
                    max_chars=self._max_chars,
                    overlap_chars=self._overlap_chars,
                )):
                    docs.append(ch["text"])
                    metas.append({"source": ch["source"], "heading": ch["heading"]})
                    ids.append(f"{rel}::{j}")
        if docs:
            col.add(documents=docs, embeddings=self._embedder(docs), metadatas=metas, ids=ids)
        self._bm25 = None  # invalidate so _ensure_bm25 rebuilds from fresh data
        self._bm25_docs = []
        self._ensure_bm25(col, docs, metas, ids)
        return len(docs)

    def _ensure_bm25(self, col=None, docs=None, metas=None, ids=None):
        if self._bm25 is not None:
            return
        from rank_bm25 import BM25Okapi

        if docs is None:
            # Lazy-load from ChromaDB (process restart case)
            col = col or self._collection()
            if col is None or col.count() == 0:
                return
            result = col.get(include=["documents", "metadatas"])
            docs = result.get("documents") or []
            metas = result.get("metadatas") or []
            ids = result.get("ids") or []

        self._bm25_docs = [
            {"id": i, "text": d, "source": m.get("source", ""), "heading": m.get("heading", "")}
            for i, d, m in zip(ids, docs, metas)
        ]
        tokenized = [list(doc["text"]) for doc in self._bm25_docs]  # char-level for Chinese
        self._bm25 = BM25Okapi(tokenized)

    def _ensure_reranker(self):
        if self._reranker is not None or not self._reranker_enabled:
            return
        try:
            import os
            from sentence_transformers import CrossEncoder
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            self._reranker = CrossEncoder(self._reranker_model, local_files_only=True)
        except Exception:
            self._reranker_enabled = False

    def _bm25_search(self, query: str, top_k: int) -> list[int]:
        """Return list of doc indices in _bm25_docs, ordered by BM25 score."""
        if self._bm25 is None:
            return []
        tokens = list(query)  # char-level tokenization for Chinese
        scores = self._bm25.get_scores(tokens)
        indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return indices[:top_k]

    def _rrf_fusion(
        self,
        dense_ids: list[str],
        bm25_indices: list[int],
    ) -> list[dict]:
        """Reciprocal Rank Fusion of dense and BM25 results."""
        k = self._rrf_k
        scores: dict[str, float] = {}

        # Build id → doc lookup from bm25_docs
        id_to_doc: dict[str, dict] = {d["id"]: d for d in self._bm25_docs}

        for rank, doc_id in enumerate(dense_ids):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)

        for rank, idx in enumerate(bm25_indices):
            if idx >= len(self._bm25_docs):
                continue
            doc_id = self._bm25_docs[idx]["id"]
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)

        sorted_ids = sorted(scores, key=lambda i: scores[i], reverse=True)
        result = []
        for doc_id in sorted_ids:
            if doc_id in id_to_doc:
                d = id_to_doc[doc_id]
                result.append({"id": d["id"], "text": d["text"], "source": d["source"], "heading": d["heading"]})
        return result

    def _rerank(self, query: str, candidates: list[dict], top_k: int) -> list[dict]:
        """Cross-encoder reranking; falls back to candidates[:top_k] if unavailable."""
        if not self._reranker_enabled:
            return candidates[:top_k]
        self._ensure_reranker()
        if self._reranker is None:
            return candidates[:top_k]
        pairs = [(query, c["text"]) for c in candidates]
        scores = self._reranker.predict(pairs)
        ranked = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
        return [c for _, c in ranked[:top_k]]

    def search(self, query: str, top_k: int = 3) -> list[dict[str, str]]:
        col = self._collection()
        if col is None or col.count() == 0:
            return []

        final_k = max(top_k, self._final_k)

        # 1. Dense retrieval
        n_dense = min(self._top_k_dense, col.count())
        res = col.query(query_embeddings=self._embedder([query]), n_results=n_dense)
        dense_ids: list[str] = (res.get("ids") or [[]])[0]

        # 2. BM25 retrieval
        self._ensure_bm25()
        bm25_indices = self._bm25_search(query, self._top_k_bm25)

        # 3. RRF fusion
        if bm25_indices:
            fused = self._rrf_fusion(dense_ids, bm25_indices)
        else:
            # BM25 not available — fall back to dense only
            docs = (res.get("documents") or [[]])[0]
            metas = (res.get("metadatas") or [[]])[0]
            fused = [{"id": did, "text": d, "source": m.get("source", ""), "heading": m.get("heading", "")}
                     for did, d, m in zip(dense_ids, docs, metas)]

        # 4. Rerank
        hits = self._rerank(query, fused, final_k)

        return hits[:top_k]


def openai_embedder(settings) -> Embedder:
    from openai import OpenAI
    base_url = settings.embedding_api_base_url or settings.openai_api_base_url
    api_key = settings.embedding_api_key or settings.openai_api_key
    client = OpenAI(base_url=base_url, api_key=api_key)

    def embed(texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            resp = client.embeddings.create(model=settings.embedding_model, input=text[:6000])
            results.append(resp.data[0].embedding)
        return results

    return embed
