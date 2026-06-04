from app.models.schemas import AnalysisRequest, ChatRequest


def test_chat_request_accepts_image_path() -> None:
    request = ChatRequest(message="分析这张图", image_path="uploads/example.jpg")

    assert request.message == "分析这张图"
    assert request.image_path == "uploads/example.jpg"


def test_analysis_request_accepts_file_id() -> None:
    request = AnalysisRequest(file_id="file_1", message="分析这张图")

    assert request.file_id == "file_1"
    assert request.image_path is None


def test_chat_request_accepts_multiple_files() -> None:
    request = ChatRequest(message="比较这三张图", file_ids=["file_1", "file_2"], image_paths=["uploads/site.jpg"])

    assert request.file_ids == ["file_1", "file_2"]
    assert request.image_paths == ["uploads/site.jpg"]
