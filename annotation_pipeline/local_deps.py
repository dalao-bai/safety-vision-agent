from __future__ import annotations

import sys
from pathlib import Path


def ensure_local_deps() -> None:
    local_deps = Path(__file__).resolve().parent.parent / ".python_deps"
    if local_deps.exists():
        sys.path.insert(0, str(local_deps))

