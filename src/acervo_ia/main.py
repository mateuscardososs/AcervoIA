from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from acervo_ia import config
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

if config.APP_ENV == "production":
    if config.STORAGE_BACKEND != "s3" or not config.S3_BUCKET:
        raise RuntimeError("Produção exige armazenamento privado S3 configurado.")
    if not config.CORS_ALLOWED_ORIGINS or any(
        not origin.startswith("https://") for origin in config.CORS_ALLOWED_ORIGINS
    ):
        raise RuntimeError("Produção exige origens CORS HTTPS explicitamente configuradas.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(config.CORS_ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)
