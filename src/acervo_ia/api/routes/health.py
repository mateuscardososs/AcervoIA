from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from acervo_ia.db.connection import ping_database

router = APIRouter(tags=["health"])


@router.get("/health", summary="Verifica se a API está respondendo")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "acervo-ia-api"}


@router.get("/health/database", summary="Verifica a conexão com o PostgreSQL")
def database_health() -> dict[str, str]:
    try:
        ping_database()
    except (RuntimeError, SQLAlchemyError) as error:
        raise HTTPException(
            status_code=503,
            detail="Não foi possível conectar ao banco de dados.",
        ) from error

    return {"status": "ok", "database": "postgresql"}