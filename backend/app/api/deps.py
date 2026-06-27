from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import Depends

from app.config import get_settings
from app.kg.store import KGStore
from app.persistence.db import Database
from app.retrieval.standards import StandardsIndex, openai_embedder
from app.correction.intake import IntakeWriter
from app.agent.orchestrator import Orchestrator
from app.agent.tools import ToolContext


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
    return StandardsIndex(
        persist_dir=s.chroma_dir,
        embedder=openai_embedder(s),
        max_chars=s.chunk_max_chars,
        overlap_chars=s.chunk_overlap_chars,
        top_k_dense=s.retrieval_top_k_dense,
        top_k_bm25=s.retrieval_top_k_bm25,
        rrf_k=s.retrieval_rrf_k,
        final_k=s.retrieval_final_k,
        reranker_model=s.reranker_model,
        reranker_enabled=s.reranker_enabled,
    )


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


def get_orchestrator(
    db: Database = Depends(get_db),
    kg: KGStore = Depends(get_kg),
    standards: StandardsIndex = Depends(get_standards),
    intake: IntakeWriter = Depends(get_intake),
    agent_client=Depends(get_agent_client),
) -> Orchestrator:
    s = get_settings()
    def _ctx(session_id: str) -> ToolContext:
        return ToolContext(db=db, kg=kg, standards=standards, intake=intake,
                           report_dir=s.report_dir, session_id=session_id)
    return Orchestrator(db=db, agent_client=agent_client, agent_model=s.agent_model,
                        ctx_factory=_ctx, max_iterations=s.max_tool_iterations,
                        max_context_chars=s.max_context_chars,
                        timeout_seconds=s.tool_loop_timeout_seconds)
