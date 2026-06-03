from app.models.schemas import ChatRequest


def test_chat_request_accepts_image_path() -> None:
    request = ChatRequest(message="分析这张图", image_path="uploads/example.jpg")

    assert request.message == "分析这张图"
    assert request.image_path == "uploads/example.jpg"
