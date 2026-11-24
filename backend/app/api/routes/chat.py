from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.hydration import PipelineFactory
from app.agent.llm import FallbackLLMRouter
from app.agent.service import ScoutAgentService
from app.api.routes.search import get_embedder, get_retrieval_service
from app.core.config import get_settings
from app.db.session import get_db
from app.ingestion.github_client import GitHubGraphQLClient
from app.ingestion.pipeline import IngestionPipeline
from app.retrieval.service import HybridRetrievalService
from app.schemas.chat import ChatHistoryResponse, ChatRequest, ScoutChatResponse

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])
SessionKey = Annotated[str, Path(min_length=2, max_length=128)]


def get_llm_router(request: Request) -> FallbackLLMRouter:
    router_client = getattr(request.app.state, "llm_router", None)
    if router_client is None:
        router_client = FallbackLLMRouter()
        request.app.state.llm_router = router_client
    return router_client


def get_pipeline_factory(request: Request) -> PipelineFactory:
    settings = get_settings()

    def pipeline_factory() -> IngestionPipeline:
        return IngestionPipeline(
            GitHubGraphQLClient(settings.github_token),
            embedder=get_embedder(request),
            settings=settings,
        )

    return pipeline_factory


async def get_agent_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    retrieval_service: Annotated[HybridRetrievalService, Depends(get_retrieval_service)],
    llm_client: Annotated[FallbackLLMRouter, Depends(get_llm_router)],
    pipeline_factory: Annotated[PipelineFactory, Depends(get_pipeline_factory)],
) -> ScoutAgentService:
    settings = get_settings()

    checkpointer = getattr(request.app.state, "checkpointer", None)
    if checkpointer is None:
        checkpointer = MemorySaver()
        request.app.state.checkpointer = checkpointer
    return ScoutAgentService(
        session,
        retrieval_service,
        llm_client,
        pipeline_factory,
        settings=settings,
        checkpointer=checkpointer,
    )


@router.post("", response_model=ScoutChatResponse)
async def chat(
    chat_request: ChatRequest,
    service: Annotated[ScoutAgentService, Depends(get_agent_service)],
) -> ScoutChatResponse:
    return await service.chat(chat_request)


@router.get("/{session_key}/history", response_model=ChatHistoryResponse)
async def chat_history(
    session_key: SessionKey,
    service: Annotated[ScoutAgentService, Depends(get_agent_service)],
) -> ChatHistoryResponse:
    return await service.get_history(session_key)
