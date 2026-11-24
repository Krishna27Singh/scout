import time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DismissedIssue, Issue, Repository, UserProfile
from app.ingestion.embedder import Embedder
from app.retrieval.filters import build_base_conditions, merge_filters
from app.retrieval.reranker import RetrievalCandidate, rerank_candidates
from app.schemas.search import SearchRequest, SearchResponse

CANDIDATE_MULTIPLIER = 5
MIN_CANDIDATES = 50


class HybridRetrievalService:
    def __init__(self, embedder: Embedder) -> None:
        self.embedder = embedder

    async def search(
        self,
        session: AsyncSession,
        request: SearchRequest,
    ) -> SearchResponse:
        start_time = time.perf_counter()
        profile: UserProfile | None = None
        dismissed_issue_ids: set[int] = set()
        if request.session_key is not None:
            profile = await session.scalar(
                select(UserProfile).where(UserProfile.session_key == request.session_key)
            )
            if profile is not None:
                dismissed_issue_ids = set(
                    (
                        await session.scalars(
                            select(DismissedIssue.issue_id).where(
                                DismissedIssue.user_profile_id == profile.id
                            )
                        )
                    ).all()
                )
        filters = merge_filters(profile, request.filters)
        conditions = build_base_conditions(filters, dismissed_issue_ids)
        candidate_limit = max(request.limit * CANDIDATE_MULTIPLIER, MIN_CANDIDATES)
        candidates: dict[int, RetrievalCandidate] = {}

        if request.mode in ("hybrid_rerank", "vector_only"):
            query_vector = self.embedder.embed_query(request.query)
            distance = Issue.embedding.cosine_distance(query_vector)
            vector_rows = await session.execute(
                select(Issue, Repository, distance)
                .join(Repository, Repository.id == Issue.repo_id)
                .where(*conditions, Issue.embedding.is_not(None))
                .order_by(distance)
                .limit(candidate_limit)
            )
            for rank, (issue, repository, raw_distance) in enumerate(vector_rows.all(), start=1):
                similarity = max(0.0, min(1.0, 1.0 - float(raw_distance)))
                candidates[issue.id] = _candidate(
                    issue,
                    repository,
                    vector_rank=rank,
                    vector_score=similarity,
                )

        if request.mode in ("hybrid_rerank", "fts_only"):
            query = func.websearch_to_tsquery("english", request.query)
            text_score = func.ts_rank_cd(Issue.search_tsv, query)
            text_rows = await session.execute(
                select(Issue, Repository, text_score)
                .join(Repository, Repository.id == Issue.repo_id)
                .where(
                    *conditions,
                    Issue.search_tsv.op("@@")(query),
                )
                .order_by(text_score.desc())
                .limit(candidate_limit)
            )
            for rank, (issue, repository, raw_score) in enumerate(text_rows.all(), start=1):
                candidate = candidates.get(issue.id)
                score = max(0.0, min(1.0, float(raw_score)))
                if candidate is None:
                    candidate = _candidate(issue, repository, fts_rank=rank, fts_score=score)
                    candidates[issue.id] = candidate
                else:
                    candidate.fts_rank = rank
                    candidate.fts_score = score

        reranked = rerank_candidates(list(candidates.values()), filters)
        if request.mode == "vector_only":
            vector_ranks = {
                candidate.id: candidate.vector_rank for candidate in candidates.values()
            }
            reranked.sort(key=lambda result: vector_ranks[result.id] or 0)
        elif request.mode == "fts_only":
            fts_ranks = {candidate.id: candidate.fts_rank for candidate in candidates.values()}
            reranked.sort(key=lambda result: fts_ranks[result.id] or 0)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return SearchResponse(
            query=request.query,
            mode=request.mode,
            applied_filters=filters,
            total_candidates=len(candidates),
            latency_ms=elapsed_ms,
            results=reranked[: request.limit],
        )


def _candidate(
    issue: Issue,
    repository: Repository,
    *,
    vector_rank: int | None = None,
    fts_rank: int | None = None,
    vector_score: float = 0.0,
    fts_score: float = 0.0,
) -> RetrievalCandidate:
    snippet = " ".join((issue.body or issue.title).split())[:280]
    return RetrievalCandidate(
        id=issue.id,
        repo_full_name=repository.full_name,
        repo_owner=repository.owner,
        repo_topics=list(repository.topics),
        primary_language=repository.primary_language,
        program_tags=list(repository.program_tags),
        number=issue.number,
        title=issue.title,
        html_url=issue.html_url,
        labels=list(issue.labels),
        comments_count=issue.comments_count,
        maintainer_activity_score=repository.maintainer_activity_score,
        github_updated_at=issue.github_updated_at,
        snippet=snippet,
        vector_rank=vector_rank,
        fts_rank=fts_rank,
        vector_score=vector_score,
        fts_score=fts_score,
    )
