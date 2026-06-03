from fastapi import APIRouter

from app.models.schemas import ReportRequest, ReportResponse
from app.services.report_generator import ReportGenerator


router = APIRouter()


@router.post("")
async def generate_report(request: ReportRequest) -> ReportResponse:
    generator = ReportGenerator()
    return generator.generate(request)
