from fastapi import FastAPI

from acervo_ia.api.routes.health import router as health_router

app = FastAPI(
    title="AcervoIA API",
    description="API para organizar e consultar documentos técnicos com fontes verificáveis.",
    version="0.1.0",
)

app.include_router(health_router)
