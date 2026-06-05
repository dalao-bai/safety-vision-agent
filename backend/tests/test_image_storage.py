"""Tests for the local image storage service (U4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.image_storage import (
    ImageValidationError,
    StoredImage,
    store_image,
)

# Minimal valid file bytes (content isn't validated beyond size in v0.1).
_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"0" * 100
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 100


def test_valid_jpeg_stored_with_generated_name(tmp_path):
    result = store_image(
        _JPEG_BYTES, "image/jpeg", str(tmp_path), max_bytes=1_000_000
    )
    assert isinstance(result, StoredImage)
    assert result.mime_type == "image/jpeg"
    assert result.byte_size == len(_JPEG_BYTES)
    assert result.stored_filename.endswith(".jpg")
    assert Path(result.stored_path).exists()
    assert Path(result.stored_path).read_bytes() == _JPEG_BYTES


def test_valid_png_stored(tmp_path):
    result = store_image(
        _PNG_BYTES, "image/png", str(tmp_path), max_bytes=1_000_000
    )
    assert result.stored_filename.endswith(".png")
    assert Path(result.stored_path).exists()


def test_returns_stable_metadata(tmp_path):
    result = store_image(
        _JPEG_BYTES, "image/jpeg", str(tmp_path), max_bytes=1_000_000
    )
    # All fields needed for repository persistence are present.
    assert result.stored_path
    assert result.stored_filename
    assert result.mime_type == "image/jpeg"
    assert result.byte_size > 0


def test_mime_with_charset_suffix_is_normalized(tmp_path):
    result = store_image(
        _JPEG_BYTES, "image/jpeg; charset=binary", str(tmp_path), max_bytes=1_000_000
    )
    assert result.mime_type == "image/jpeg"


def test_unsupported_mime_rejected(tmp_path):
    with pytest.raises(ImageValidationError) as exc_info:
        store_image(b"GIF89a", "image/gif", str(tmp_path), max_bytes=1_000_000)
    assert "unsupported" in str(exc_info.value).lower()


def test_oversized_image_rejected_and_not_written(tmp_path):
    big = b"0" * 2000
    with pytest.raises(ImageValidationError) as exc_info:
        store_image(big, "image/jpeg", str(tmp_path), max_bytes=1000)
    assert "too large" in str(exc_info.value).lower()
    # No file should have been written.
    assert list(tmp_path.iterdir()) == []


def test_empty_upload_rejected(tmp_path):
    with pytest.raises(ImageValidationError):
        store_image(b"", "image/jpeg", str(tmp_path), max_bytes=1000)


def test_client_filename_does_not_affect_stored_path(tmp_path):
    # store_image takes no client filename at all; the stored name is generated.
    # This documents/guards that contract: two stores never collide and the
    # name is always a safe hex + known extension.
    r1 = store_image(_JPEG_BYTES, "image/jpeg", str(tmp_path), max_bytes=1_000_000)
    r2 = store_image(_JPEG_BYTES, "image/jpeg", str(tmp_path), max_bytes=1_000_000)
    assert r1.stored_filename != r2.stored_filename
    # No path traversal characters in generated names.
    for name in (r1.stored_filename, r2.stored_filename):
        assert "/" not in name and "\\" not in name and ".." not in name
