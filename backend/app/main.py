import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response
from starlette.staticfiles import StaticFiles

from app.agent.llm import FallbackLLMRouter
from app.api.routes.chat import router as chat_router
from app.api.routes.health import router as health_router
from app.api.routes.profiles import router as profiles_router
from app.api.routes.search import router as search_router
from app.core.config import get_settings
from app.core.logging import configure_logging, request_id_context
from app.ingestion.embedder import FastEmbedder

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    pool: AsyncConnectionPool[AsyncConnection[dict[str, Any]]] | None = None
    try:
        if settings.app_env.casefold() == "production":
            connection_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
            pool = AsyncConnectionPool(
                conninfo=connection_url,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                },
                min_size=1,
                max_size=5,
                open=False,
            )
            await pool.open()
            checkpointer = AsyncPostgresSaver(pool)
            await checkpointer.setup()
            application.state.checkpointer = checkpointer
            application.state.checkpoint_pool = pool
        yield
    finally:
        llm_router = getattr(application.state, "llm_router", None)
        if llm_router is not None:
            await llm_router.aclose()
        if pool is not None:
            await pool.close()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    application = FastAPI(title="Scout", version="0.1.0", lifespan=lifespan)
    application.state.embedder = FastEmbedder()
    application.state.llm_router = FallbackLLMRouter(settings)
    application.state.checkpointer = MemorySaver()
    application.mount(
        "/static",
        StaticFiles(directory=str(_FRONTEND_DIR)),
        name="static",
    )
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
    application.include_router(chat_router)

    @application.get("/", include_in_schema=False)
    async def frontend_index() -> FileResponse:
        return FileResponse(
            _FRONTEND_DIR / "index.html",
            headers={"Cache-Control": "no-cache"},
        )

    return application


app = create_app()
