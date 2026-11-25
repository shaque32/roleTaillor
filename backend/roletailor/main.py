"""FastAPI application factory. Run with: uvicorn roletailor.main:create_app --factory"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from roletailor.api.errors import install_error_handlers
from roletailor.api.middleware import RequestContextMiddleware
from roletailor.api.ratelimit import RateLimiter
from roletailor.api.routes import applications, auth, billing, jobs, me, ops, resumes, review, workflows
from roletailor.config import get_settings
from roletailor.logging_setup import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="RoleTailor API", version="1.0.0", docs_url="/docs", openapi_url="/openapi.json")
    app.state.limiter = RateLimiter(settings.redis_url)

    v1 = APIRouter(prefix="/v1")
    for module in (auth, me, resumes, jobs, workflows, review, applications, billing):
        v1.include_router(module.router)
    app.include_router(v1)
    app.include_router(ops.router)

    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Correlation-ID",
                       "X-Organization-ID"],
        expose_headers=["X-Correlation-ID", "Retry-After"],
    )
    app.add_middleware(RequestContextMiddleware)
    return app
