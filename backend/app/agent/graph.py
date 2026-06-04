from app.agent.executor import ReActSafetyAgent
from app.agent.state import SafetyAgentState


async def run_safety_agent(state: SafetyAgentState) -> SafetyAgentState:
    """Compatibility entrypoint for the backend Agent.

    The old fixed LangGraph router has been replaced by a bounded ReAct loop.
    The function name stays stable for API and test callers.
    """

    return await ReActSafetyAgent().run(dict(state))
