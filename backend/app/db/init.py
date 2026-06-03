from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.config import get_settings
from app.db import models
from app.db.session import Base, engine


def create_db_and_tables() -> None:
    Base.metadata.create_all(bind=engine)


def run_migrations() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    alembic_ini = backend_dir / "alembic.ini"
    if not alembic_ini.exists():
        create_db_and_tables()
        return

    settings = get_settings()
    config = Config(alembic_ini.as_posix())
    config.set_main_option("script_location", (backend_dir / "alembic").as_posix())
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


__all__ = ["create_db_and_tables", "run_migrations", "models"]
