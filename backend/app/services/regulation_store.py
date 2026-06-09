"""规范库语义检索存储 (v0.2)。

把上传的 PDF / Word 规范解析为纯文本、切分为 chunk，用注入的 embed_fn 算
向量后写入 ChromaDB，供 Agent 工具做语义检索。向量计算通过构造参数注入，
生产用 responses_client.embed，测试注入 fake，因此本模块不依赖网络。

关键约束：所有写入 / 查询都显式传 embeddings / query_embeddings，绝不触发
ChromaDB 的默认嵌入模型下载（collection 的 embedding_function 设为 None）。
"""

from __future__ import annotations

from typing import Callable

import chromadb
import pdfplumber
from docx import Document

# 批量文本 -> 向量的可注入函数签名。
EmbedFn = Callable[[list[str]], list[list[float]]]

_COLLECTION_NAME = "regulations"


class RegulationStore:
    """规范文本的向量存储与检索。

    Args:
        chroma_dir: ChromaDB 持久化目录。
        embed_fn: 把一批文本映射为一批向量的函数（顺序保持）。
    """

    def __init__(self, chroma_dir: str, embed_fn: EmbedFn):
        self._embed_fn = embed_fn
        self._client = chromadb.PersistentClient(path=chroma_dir)
        # embedding_function=None：本库自带向量，禁止 Chroma 自行下载模型。
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME, embedding_function=None
        )

    # --- 解析 ---------------------------------------------------------------

    def parse_file(self, path: str, file_type: str) -> str:
        """解析 pdf / docx 为纯文本。file_type 不支持时抛 ValueError。"""
        ftype = file_type.lower().lstrip(".")
        if ftype == "pdf":
            return self._parse_pdf(path)
        if ftype == "docx":
            return self._parse_docx(path)
        raise ValueError(f"unsupported file_type: {file_type}")

    @staticmethod
    def _parse_pdf(path: str) -> str:
        parts: list[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    parts.append(text)
        return "\n".join(parts)

    @staticmethod
    def _parse_docx(path: str) -> str:
        doc = Document(path)
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(parts)

    # --- 切分 ---------------------------------------------------------------

    def chunk_text(self, text: str, size: int = 800, overlap: int = 100) -> list[str]:
        """滑动窗口切分。相邻 chunk 重叠 overlap 个字符以保留上下文。"""
        if size <= overlap:
            raise ValueError("size must be greater than overlap")
        text = text.strip()
        if not text:
            return []

        chunks: list[str] = []
        start = 0
        n = len(text)
        step = size - overlap
        while start < n:
            chunk = text[start : start + size]
            if chunk.strip():
                chunks.append(chunk)
            if start + size >= n:
                break
            start += step
        return chunks

    # --- 写入 / 检索 / 删除 -------------------------------------------------

    def add_regulation(
        self, regulation_file_id: str, original_name: str, chunks: list[str]
    ) -> int:
        """算向量后写入 collection，返回写入的 chunk 数。"""
        if not chunks:
            return 0
        embeddings = self._embed_fn(chunks)
        ids = [f"{regulation_file_id}:{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "regulation_file_id": regulation_file_id,
                "original_name": original_name,
                "chunk_index": i,
                "text": chunk,
            }
            for i, chunk in enumerate(chunks)
        ]
        self._collection.add(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=chunks,
        )
        return len(chunks)

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        """语义检索，返回 [{text, original_name, regulation_file_id, distance}]。"""
        query_embedding = self._embed_fn([query])
        result = self._collection.query(
            query_embeddings=query_embedding,
            n_results=top_k,
            include=["metadatas", "distances"],
        )
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        out: list[dict] = []
        for meta, dist in zip(metadatas, distances):
            out.append(
                {
                    "text": meta.get("text", ""),
                    "original_name": meta.get("original_name", ""),
                    "regulation_file_id": meta.get("regulation_file_id", ""),
                    "distance": dist,
                }
            )
        return out

    def delete_regulation(self, regulation_file_id: str) -> None:
        """按 metadata 删除某规范文件的全部 chunk。"""
        self._collection.delete(where={"regulation_file_id": regulation_file_id})
