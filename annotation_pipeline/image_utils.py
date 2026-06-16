from __future__ import annotations

import base64
import binascii
import mimetypes
import re
from pathlib import Path

from .constants import IMAGE_SUFFIXES
from .local_deps import ensure_local_deps

ensure_local_deps()

try:
    from PIL import Image
except Exception:
    Image = None


def image_dimensions(path: Path) -> tuple[int, int]:
    if Image is not None:
        with Image.open(path) as image:
            return image.size
    data = path.read_bytes()[:32]
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        return width, height
    if data.startswith(b"\xff\xd8"):
        return jpeg_size(path)
    raise ValueError(f"unsupported image type without Pillow: {path}")


def jpeg_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as f:
        if f.read(2) != b"\xff\xd8":
            raise ValueError(f"not a JPEG file: {path}")
        while True:
            marker_start = f.read(1)
            if not marker_start:
                break
            if marker_start != b"\xff":
                continue
            marker = f.read(1)
            while marker == b"\xff":
                marker = f.read(1)
            if marker in {b"\xc0", b"\xc1", b"\xc2", b"\xc3", b"\xc5", b"\xc6", b"\xc7", b"\xc9", b"\xca", b"\xcb", b"\xcd", b"\xce", b"\xcf"}:
                f.read(3)
                height = int.from_bytes(f.read(2), "big")
                width = int.from_bytes(f.read(2), "big")
                return width, height
            size = int.from_bytes(f.read(2), "big")
            f.seek(size - 2, 1)
    raise ValueError(f"cannot read JPEG size: {path}")


def image_to_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def stable_sample_id(image_path: Path) -> str:
    stem = image_path.stem
    if re.fullmatch(r"foe_[0-9]{6}", stem):
        return stem
    value = binascii.crc32(image_path.as_posix().encode("utf-8")) % 1_000_000
    return f"foe_{value:06d}"


def find_images(image_dir: Path, single_image: str | None = None) -> list[Path]:
    if single_image:
        return [Path(single_image)]
    return sorted(p for p in image_dir.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)

