from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

import chromadb

Embedder = Callable[[list[str]], list[list[float]]]

_COLLECTION = "standards"


def chunk_markdown(md: str, source: str) -> list[dict[str, str]]:
    """Split markdown into chunks at headings; keep heading with its body."""
    parts = re.split(r"(?m)^(#{1,6}\s.*)$", md)
    chunks: list[dict[str, str]] = []
    pre = parts[0].strip()
    if pre:
        chunks.append({"text": pre, "source": source, "heading": ""})
    for i in range(1, len(parts), 2):
        heading = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        text = (heading + "\n" + body).strip()
        if text:
            chunks.append({"text": text, "source": source, "heading": heading})
    return chunks


class StandardsIndex:
    def __init__(self, persist_dir: str, embedder: Embedder):
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._embedder = embedder

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
                for j, ch in enumerate(chunk_markdown(md, source=rel)):
                    docs.append(ch["text"])
                    metas.append({"source": ch["source"], "heading": ch["heading"]})
                    ids.append(f"{rel}::{j}")
        if docs:
            col.add(documents=docs, embeddings=self._embedder(docs), metadatas=metas, ids=ids)
        return len(docs)

    def search(self, query: str, top_k: int = 3) -> list[dict[str, str]]:
        col = self._collection()
        if col is None or col.count() == 0:
            return []
        n = min(top_k, col.count())
        res = col.query(query_embeddings=self._embedder([query]), n_results=n)
        hits: list[dict[str, str]] = []
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        for text, meta in zip(docs, metas):
            hits.append({"text": text, "source": meta.get("source", ""), "heading": meta.get("heading", "")})
        return hits


def openai_embedder(settings) -> Embedder:
    from openai import OpenAI
    client = OpenAI(base_url=settings.openai_api_base_url, api_key=settings.openai_api_key)

    def embed(texts: list[str]) -> list[list[float]]:
        resp = client.embeddings.create(model=settings.embedding_model, input=texts)
        return [d.embedding for d in resp.data]

    return embed
