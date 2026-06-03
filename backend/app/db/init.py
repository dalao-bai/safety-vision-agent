from app.db import models
from app.db.session import Base, engine


def create_db_and_tables() -> None:
    Base.metadata.create_all(bind=engine)


__all__ = ["create_db_and_tables", "models"]
