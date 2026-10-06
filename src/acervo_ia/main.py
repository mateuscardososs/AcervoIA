from fastapi import FastAPI

from acervo_ia.api.routes.auth import router as auth_router
from acervo_ia.api.routes.collections import router as collections_router
from acervo_ia.api.routes.documents import router as documents_router
from acervo_ia.api.routes.embeddings import router as embeddings_router
from acervo_ia.api.routes.health import router as health_router
from acervo_ia.api.routes.qa import router as qa_router

app = FastAPI(
    title="AcervoIA API",
    description="API para organizar e consultar documentos técnicos com fontes verificáveis.",
    version="0.1.0",
)

app.include_router(health_router)
app.include_router(qa_router)
app.include_router(auth_router)
app.include_router(collections_router)
app.include_router(documents_router)
app.include_router(embeddings_router)
