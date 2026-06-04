from fastapi import APIRouter, HTTPException

from app.agents.safety_expert import SafetyExpertAgent
from app.db.repositories import latest_fused_result
from app.models.schemas import AnalysisRequest, AnalysisResponse, AnalysisResultResponse, ChatRequest, FusedResult, TaskStatusResponse


router = APIRouter()


@router.post("", response_model=AnalysisResponse)
async def create_analysis(request: AnalysisRequest) -> AnalysisResponse:
    response = await SafetyExpertAgent().handle(
        ChatRequest(
            conversation_id=request.conversation_id,
            message=request.message,
            file_id=request.file_id,
            file_ids=request.file_ids,
            image_path=request.image_path,
            image_paths=request.image_paths,
            selected_bbox=request.selected_bbox,
        )
    )
    if not response.latest_analysis_id:
        raise HTTPException(status_code=400, detail=response.answer)
    status = "failed" if response.errors else "completed"
    return AnalysisResponse(
        analysis_id=response.latest_analysis_id,
        conversation_id=response.conversation_id,
        task_id=response.latest_analysis_id,
        status=status,
    )


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
def get_task_status(task_id: str) -> TaskStatusResponse:
    record = latest_fused_result(task_id)
    if not record:
        return TaskStatusResponse(task_id=task_id, status="failed", error="analysis result not found")
    return TaskStatusResponse(task_id=task_id, status="completed", result=record.result_json)


@router.get("/{analysis_id}", response_model=AnalysisResultResponse)
def get_analysis_result(analysis_id: str) -> AnalysisResultResponse:
    record = latest_fused_result(analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="analysis result not found")
    return AnalysisResultResponse(
        analysis_id=analysis_id,
        status="completed",
        result=FusedResult.model_validate(record.result_json),
    )
