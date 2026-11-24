from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DismissedIssue, Issue, UserProfile
from app.db.session import get_db
from app.ingestion.embedder import Embedder, FastEmbedder
from app.retrieval.service import HybridRetrievalService
from app.schemas.search import SearchRequest, SearchResponse

router = APIRouter(prefix="/api/v1", tags=["search"])
SessionKey = Annotated[str, Path(min_length=1, max_length=128)]


class DismissRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    issue_id: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=256)


def get_embedder(request: Request) -> Embedder:
    embedder = getattr(request.app.state, "embedder", None)
    if embedder is None:
        embedder = FastEmbedder()
        request.app.state.embedder = embedder
    return embedder


def get_retrieval_service(
    embedder: Annotated[Embedder, Depends(get_embedder)],
) -> HybridRetrievalService:
    return HybridRetrievalService(embedder)


@router.post("/search", response_model=SearchResponse)
async def search_issues(
    search_request: SearchRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[HybridRetrievalService, Depends(get_retrieval_service)],
) -> SearchResponse:
    return await service.search(db, search_request)


@router.post(
    "/profiles/{session_key}/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def dismiss_issue(
    session_key: SessionKey,
    dismiss_request: DismissRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    profile = await db.scalar(select(UserProfile).where(UserProfile.session_key == session_key))
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    issue_exists = await db.scalar(select(Issue.id).where(Issue.id == dismiss_request.issue_id))
    if issue_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")

    statement = insert(DismissedIssue).values(
        user_profile_id=profile.id,
        issue_id=dismiss_request.issue_id,
        reason=dismiss_request.reason,
    )
    await db.execute(
        statement.on_conflict_do_nothing(
            index_elements=[DismissedIssue.user_profile_id, DismissedIssue.issue_id]
        )
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
