from app.models.schemas import AnalysisRequest, ChatRequest


def test_chat_request_accepts_image_path() -> None:
    request = ChatRequest(message="分析这张图", image_path="uploads/example.jpg")

    assert request.message == "分析这张图"
    assert request.image_path == "uploads/example.jpg"


def test_analysis_request_accepts_file_id() -> None:
    request = AnalysisRequest(file_id="file_1", message="分析这张图")

    assert request.file_id == "file_1"
    assert request.image_path is None
