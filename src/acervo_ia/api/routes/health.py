from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", summary="Verifica se a API está respondendo")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "acervo-ia-api"}
