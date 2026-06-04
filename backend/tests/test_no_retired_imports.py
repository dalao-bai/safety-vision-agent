from pathlib import Path


RETIRED_IMPORTS = ("celery", "redis", "sqlalchemy", "alembic", "psycopg", "pydantic_settings")


def test_active_backend_does_not_import_retired_infrastructure() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in RETIRED_IMPORTS:
            if f"import {name}" in text or f"from {name}" in text:
                offenders.append(f"{path.relative_to(root)} imports {name}")

    assert offenders == []
