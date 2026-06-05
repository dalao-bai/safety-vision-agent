"""Local image storage service (U4).

Validates an uploaded image (MIME type, size), writes it to the local uploads
directory under a generated safe filename, and returns metadata for repository
persistence. No HTTP or external-model concerns here — that wiring is in U8.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

# Allowed image MIME types mapped to canonical file extensions.
_ALLOWED_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class ImageValidationError(ValueError):
    """Raised when an uploaded image fails validation (type or size)."""


@dataclass(frozen=True)
class StoredImage:
    """Result of storing an uploaded image."""

    stored_path: str
    stored_filename: str
    mime_type: str
    byte_size: int


def store_image(
    data: bytes,
    mime_type: str,
    upload_dir: str,
    max_bytes: int,
) -> StoredImage:
    """Validate and store image bytes under ``upload_dir``.

    Generates a server-side filename rather than trusting any client-provided
    name, so unsafe original filenames cannot influence the stored path.

    Raises ImageValidationError for unsupported MIME types or oversized images.
    """
    normalized_mime = (mime_type or "").split(";")[0].strip().lower()
    if normalized_mime not in _ALLOWED_MIME:
        raise ImageValidationError(
            f"unsupported image type: {mime_type!r}. "
            f"Allowed: {', '.join(sorted(_ALLOWED_MIME))}"
        )

    byte_size = len(data)
    if byte_size == 0:
        raise ImageValidationError("empty image upload")
    if byte_size > max_bytes:
        raise ImageValidationError(
            f"image too large: {byte_size} bytes exceeds limit of {max_bytes} bytes"
        )

    extension = _ALLOWED_MIME[normalized_mime]
    stored_filename = f"{uuid.uuid4().hex}{extension}"

    dir_path = Path(upload_dir)
    dir_path.mkdir(parents=True, exist_ok=True)
    stored_path = dir_path / stored_filename
    stored_path.write_bytes(data)

    return StoredImage(
        stored_path=str(stored_path),
        stored_filename=stored_filename,
        mime_type=normalized_mime,
        byte_size=byte_size,
    )
