from pathlib import Path

import pytest
from fastapi import HTTPException

from app.core.config import get_settings
from app.services.file_storage import validate_uploaded_path


def test_validate_uploaded_path_rejects_path_outside_upload_dir() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_uploaded_path("/etc/passwd")

    assert exc_info.value.status_code == 400


def test_validate_uploaded_path_accepts_file_inside_upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "upload_dir", tmp_path.as_posix())
    image = tmp_path / "image.jpg"
    image.write_bytes(b"fake image")

    assert validate_uploaded_path(image.as_posix()) == image.as_posix()
