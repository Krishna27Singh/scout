import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.api.routes.health import router as health_router
from app.api.routes.profiles import router as profiles_router
from app.api.routes.search import router as search_router
from app.core.config import get_settings
from app.core.logging import configure_logging, request_id_context
from app.ingestion.embedder import FastEmbedder

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    application = FastAPI(title="Scout", version="0.1.0", lifespan=lifespan)
    application.state.embedder = FastEmbedder()
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def request_id_middleware(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        candidate = request.headers.get("X-Request-ID", "")
        request_id = candidate if _REQUEST_ID_PATTERN.fullmatch(candidate) else str(uuid4())
        token = request_id_context.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_context.reset(token)

    application.include_router(health_router)
    application.include_router(profiles_router)
    application.include_router(search_router)
    return application


app = create_app()
