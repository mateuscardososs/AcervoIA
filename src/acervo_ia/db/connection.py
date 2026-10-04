import os
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


class DatabaseUnavailableError(RuntimeError):
    """Indicates database unavailability without exposing connection details."""


@lru_cache
def get_engine() -> Engine:
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise DatabaseUnavailableError("Banco de dados indisponível.")

    return create_engine(database_url, pool_pre_ping=True)


def ping_database() -> None:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        pass
    else:
        return

    raise DatabaseUnavailableError("Banco de dados indisponível.") from None


def get_db() -> Iterator[Session]:
    try:
        with Session(get_engine()) as session:
            yield session
    except SQLAlchemyError:
        pass
    else:
        return

    raise DatabaseUnavailableError("Banco de dados indisponível.") from None
