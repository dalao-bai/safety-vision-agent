import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from langgraph.graph import END, StateGraph

from app.agent import nodes
from app.agent.router import route_after_classification
from app.agent.state import SafetyAgentState


def analyze_image_sync(state: dict) -> dict:
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(nodes.analyze_image(state))).result()


@lru_cache
def build_langgraph():
    graph = StateGraph(SafetyAgentState)

    graph.add_node("load_context", nodes.load_context)
    graph.add_node("classify", nodes.classify)
    graph.add_node("analyze", analyze_image_sync)
    graph.add_node("rule_basis", nodes.answer_rule_basis)
    graph.add_node("remediation", nodes.create_remediation)
    graph.add_node("report", nodes.generate_report)
    graph.add_node("evidence_gap", nodes.answer_evidence_gap)
    graph.add_node("memory_answer", nodes.answer_from_memory)
    graph.add_node("need_image", nodes.need_image)
    graph.add_node("persist_turn", nodes.persist_turn)

    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "classify")
    graph.add_conditional_edges(
        "classify",
        route_after_classification,
        {
            "analyze": "analyze",
            "rule_basis": "rule_basis",
            "remediation": "remediation",
            "report": "report",
            "evidence_gap": "evidence_gap",
            "memory_answer": "memory_answer",
            "need_image": "need_image",
        },
    )
    for node_name in ["analyze", "rule_basis", "remediation", "report", "evidence_gap", "memory_answer", "need_image"]:
        graph.add_edge(node_name, "persist_turn")
    graph.add_edge("persist_turn", END)

    return graph.compile()


async def run_safety_agent(state: SafetyAgentState) -> SafetyAgentState:
    current: SafetyAgentState = dict(state)
    for update in build_langgraph().stream(state, stream_mode="updates"):
        current = next(iter(update.values()))
    return current
