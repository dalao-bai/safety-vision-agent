"""Build the standards vector index (RAG) from the KG standard OCR markdown.

Run from the backend/ directory:
    cd backend && python scripts/build_standards_index.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# allow running as a plain script: ensure backend/ is on sys.path so `app` imports work
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.retrieval.standards import StandardsIndex, openai_embedder


def main() -> int:
    settings = get_settings()
    repo_root = Path(__file__).resolve().parents[2]
    standards_root = repo_root / "知识图谱主文件" / "标准规范文件"
    if not standards_root.exists():
        print(f"standards dir not found: {standards_root}", file=sys.stderr)
        return 1
    idx = StandardsIndex(persist_dir=settings.chroma_dir, embedder=openai_embedder(settings))
    n = idx.build([standards_root])
    print(f"indexed {n} chunks into {settings.chroma_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
