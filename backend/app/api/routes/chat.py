from fastapi import APIRouter

from app.agents.safety_expert import SafetyExpertAgent
from app.models.schemas import ChatRequest, ChatResponse


router = APIRouter()


@router.post("")
async def chat(request: ChatRequest) -> ChatResponse:
    agent = SafetyExpertAgent()
    return await agent.handle(request)
