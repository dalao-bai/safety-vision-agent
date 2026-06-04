from app.agent import nodes
from app.agent.state import SafetyAgentState


class SafetyAgentRunner:
    async def ainvoke(self, state: SafetyAgentState) -> SafetyAgentState:
        current = nodes.load_context(dict(state))
        current = nodes.classify(current)
        intent = current.get("intent")

        if intent == "analyze":
            current = await nodes.analyze_image(current)
        elif intent == "rule_basis":
            current = nodes.answer_rule_basis(current)
        elif intent == "remediation":
            current = nodes.create_remediation(current)
        elif intent == "report":
            current = nodes.generate_report(current)
        elif intent == "evidence_gap":
            current = nodes.answer_evidence_gap(current)
        elif intent == "memory_answer":
            current = nodes.answer_from_memory(current)
        else:
            current = nodes.need_image(current)

        return nodes.persist_turn(current)


async def run_safety_agent(state: SafetyAgentState) -> SafetyAgentState:
    return await SafetyAgentRunner().ainvoke(state)
