import os
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


@lru_cache
def get_engine() -> Engine:
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("A variável DATABASE_URL não foi configurada.")

    return create_engine(database_url, pool_pre_ping=True)


def ping_database() -> None:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))