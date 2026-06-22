from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.kg.store import KGStore
from app.persistence.db import Database
from app.retrieval.standards import StandardsIndex, openai_embedder
from app.correction.intake import IntakeWriter


@lru_cache
def get_db() -> Database:
    return Database(get_settings().database_path)


@lru_cache
def get_kg() -> KGStore:
    root = Path(__file__).resolve().parents[3]
    return KGStore.load(str(root / "知识图谱主文件" / "four_openings_edges_kg_v2.json"))


@lru_cache
def get_standards() -> StandardsIndex:
    s = get_settings()
    return StandardsIndex(persist_dir=s.chroma_dir, embedder=openai_embedder(s))


@lru_cache
def get_intake() -> IntakeWriter:
    return IntakeWriter(get_settings().pipeline_intake_dir)


@lru_cache
def get_agent_client():
    from openai import OpenAI
    s = get_settings()
    return OpenAI(base_url=s.openai_api_base_url, api_key=s.openai_api_key)


@lru_cache
def get_detector():
    from app.vlm.detector import build_detector
    return build_detector(get_settings(), get_kg())
