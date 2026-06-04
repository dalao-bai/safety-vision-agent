from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.config import get_settings
from app.db import models
from app.db.session import Base, engine
from app.services.file_storage import ensure_runtime_dirs


def create_db_and_tables() -> None:
    ensure_runtime_dirs()
    Base.metadata.create_all(bind=engine)


def run_migrations() -> None:
    ensure_runtime_dirs()
    backend_dir = Path(__file__).resolve().parents[2]
    alembic_ini = backend_dir / "alembic.ini"
    if not alembic_ini.exists():
        create_db_and_tables()
        return

    settings = get_settings()
    config = Config(alembic_ini.as_posix())
    config.set_main_option("script_location", (backend_dir / "alembic").as_posix())
    config.set_main_option("sqlalchemy.url", settings.sqlalchemy_database_url)
    command.upgrade(config, "head")


__all__ = ["create_db_and_tables", "run_migrations", "models"]
