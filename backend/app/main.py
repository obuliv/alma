from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import documents, health
from app.config import settings


def create_app() -> FastAPI:
    app = FastAPI(title="Alma Document Upload API", version="0.1.0")

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Ensure the upload directory exists at startup.
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)

    app.include_router(health.router, prefix="/api")
    app.include_router(documents.router, prefix="/api")
    return app


app = create_app()
