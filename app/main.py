from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import get_settings
from app.core.database import async_engine, import_all_models
from app.core.ratelimit import limiter
from app.core.seed import seed
from app.dzz_service.routers import connection_router, proxy_router
from app.layers_service.routers import folders_router, import_export_router, layers_router, objects_router
from app.ml_service.routers import router as models_router
from app.activity_service.routers import router as activity_router
from app.tasks_service.routers import router as tasks_router
from app.users_service.routers import auth_router, profile_router

import_all_models()
settings = get_settings()


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = b""
        for key, value in scope.get("headers") or []:
            if key == b"x-request-id":
                request_id = value
                break
        if not request_id:
            request_id = str(uuid.uuid4()).encode()

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.extend(
                    [
                        (b"x-request-id", request_id),
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                    ]
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        seed()
    except Exception:
        logging.getLogger(__name__).exception("startup seed failed")
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="АгроВижион API",
        version="1.0.0",
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
        lifespan=lifespan,
    )
    application.add_middleware(RequestContextMiddleware)
    application.state.limiter = limiter
    application.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.exception_handler(Exception)
    async def unhandled_error(_request: Request, exc: Exception):
        if isinstance(exc, (HTTPException, StarletteHTTPException)):
            raise exc
        if settings.app_env == "dev":
            return JSONResponse({"detail": str(exc)}, status_code=500)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    prefix = "/api/v1"
    application.include_router(auth_router, prefix=prefix)
    application.include_router(profile_router, prefix=prefix)
    application.include_router(activity_router, prefix=prefix)
    application.include_router(layers_router, prefix=prefix)
    application.include_router(objects_router, prefix=prefix)
    application.include_router(folders_router, prefix=prefix)
    application.include_router(import_export_router, prefix=prefix)
    application.include_router(tasks_router, prefix=prefix)
    application.include_router(models_router, prefix=prefix)
    application.include_router(connection_router, prefix=prefix)
    application.include_router(proxy_router, prefix=prefix)

    @application.get(f"{prefix}/health")
    async def health():
        return {"status": "ok"}

    @application.get("/health")
    async def health_root():
        return {"status": "ok"}

    @application.get("/docs")
    async def docs_redirect():
        return RedirectResponse(url="/api/v1/docs")

    @application.get(f"{prefix}/ready")
    async def ready():
        try:
            async with async_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                version = await conn.execute(text("SELECT version_num FROM alembic_version"))
                if version.scalar() is None:
                    return JSONResponse({"status": "not_ready", "detail": "migrations missing"}, status_code=503)
        except Exception as exc:
            return JSONResponse({"status": "not_ready", "detail": str(exc)}, status_code=503)
        return {"status": "ready"}

    return application


app = create_app()
