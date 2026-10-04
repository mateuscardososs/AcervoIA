import logging

from fastapi import APIRouter, HTTPException

from acervo_ia.db.connection import DatabaseUnavailableError, ping_database

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", summary="Verifica se a API está respondendo")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "acervo-ia-api"}


@router.get("/health/database", summary="Verifica a conexão com o PostgreSQL")
def database_health() -> dict[str, str]:
    try:
        ping_database()
    except DatabaseUnavailableError:
        logger.warning("Falha na verificação do banco de dados.")
        raise HTTPException(
            status_code=503,
            detail="Não foi possível conectar ao banco de dados.",
        ) from None

    return {"status": "ok", "database": "postgresql"}
