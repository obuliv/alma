from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import applications, documents, form_fill, health
from app.config import settings
from app.core.errors import AppError
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Alma Document Upload API", version="0.1.0")

    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

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
    app.include_router(applications.router, prefix="/api")
    app.include_router(form_fill.router, prefix="/api")
    return app


app = create_app()
