from fastapi import APIRouter

from app.agents.safety_expert import SafetyExpertAgent
from app.models.schemas import AgentChatRequest, AgentChatResponse


router = APIRouter()


@router.post("", response_model=AgentChatResponse)
async def chat(request: AgentChatRequest) -> AgentChatResponse:
    agent = SafetyExpertAgent()
    return await agent.handle(request)
