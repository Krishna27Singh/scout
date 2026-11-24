from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm import DeterministicRuleBasedLLM, FallbackLLMRouter, StructuredLLMClient
from app.agent.service import ScoutAgentService
from app.core.config import get_settings
from app.db.models import Issue, Repository, UserProfile
from app.db.session import SessionFactory, engine
from app.ingestion.embedder import DeterministicFakeEmbedder
from app.ingestion.github_client import FetchedIssue, FetchedRepoBatch, FetchedRepository
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.seed import RepoTarget
from app.retrieval.service import HybridRetrievalService
from app.schemas.chat import AgentPlan, ChatRequest, ScoutChatResponse


class _EvalGitHubClient:
    def __init__(self, batch: FetchedRepoBatch) -> None:
        self.batch = batch
        self.calls = 0

    async def fetch_repository_issues(
        self,
        owner: str,
        name: str,
        since: datetime | None = None,
        max_issues: int = 120,
    ) -> FetchedRepoBatch:
        del owner, name, since, max_issues
        self.calls += 1
        return self.batch

    async def fetch_org_active_repos(self, org: str, limit: int = 10) -> list[RepoTarget]:
        del org, limit
        return []

    async def aclose(self) -> None:
        return None


@dataclass(frozen=True)
class AgentEvalMetrics:
    json_schema_pass_rate: float
    memory_persistence_rate: float
    groundedness_rate: float
    hydration_trigger_accuracy: float


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate Scout's conversational agent")
    parser.add_argument(
        "--mode",
        choices=("deterministic", "live"),
        default="deterministic",
    )
    return parser


async def _run_evaluations(mode: str) -> AgentEvalMetrics:
    settings = get_settings().model_copy(update={"github_token": "agent-eval-token"})
    llm_client: StructuredLLMClient
    if mode == "deterministic":
        llm_client = DeterministicRuleBasedLLM()
    else:
        if not settings.groq_api_key and not settings.gemini_api_key:
            raise RuntimeError("Live evaluation requires GROQ_API_KEY or GEMINI_API_KEY")
        llm_client = FallbackLLMRouter(settings)

    schema_passes = await _schema_pass_rate(llm_client)
    suffix = uuid4().hex[:12]
    session_key = f"agent-eval-{suffix}"
    seed_repo = f"agent-eval-{suffix}/python-parser"
    jit_repo = f"agent-jit-{suffix}/fresh-parser"
    embedder = DeterministicFakeEmbedder()
    service = HybridRetrievalService(embedder)
    github_client = _build_eval_github_client(jit_repo)

    def pipeline_factory() -> IngestionPipeline:
        return IngestionPipeline(
            github_client,
            embedder=embedder,
            settings=settings,
        )

    repo_names = [seed_repo, jit_repo]
    try:
        async with SessionFactory() as session:
            try:
                await _seed_memory_benchmark(session, seed_repo, embedder)
                agent = ScoutAgentService(
                    session,
                    service,
                    llm_client,
                    pipeline_factory,
                    settings=settings,
                )
                await agent.chat(
                    ChatRequest(
                        session_key=session_key,
                        message="I want Python GSoC issues, never documentation",
                    )
                )
                follow_up = await agent.chat(
                    ChatRequest(
                        session_key=session_key,
                        message="Show me parser or math bugs",
                    )
                )
                memory_ok = (
                    "python" in follow_up.applied_filters.languages
                    and "documentation" in follow_up.applied_filters.excluded_labels
                    and all(
                        "documentation" not in {label.casefold() for label in match.issue.labels}
                        for match in follow_up.matches
                    )
                )
                grounded = await _groundedness_rate(session, follow_up)

                first_hydration = await agent.chat(
                    ChatRequest(
                        session_key=session_key,
                        message=f"Find Python parser issues in {jit_repo}",
                    )
                )
                second_hydration = await agent.chat(
                    ChatRequest(
                        session_key=session_key,
                        message=f"Show parser bugs in {jit_repo}",
                    )
                )
                hydration_accuracy = (
                    sum(
                        (
                            first_hydration.hydration.status == "hydrated"
                            and first_hydration.hydration.triggered
                            and bool(first_hydration.hydration.repos_synced),
                            second_hydration.hydration.status == "not_needed"
                            and not second_hydration.hydration.triggered,
                        )
                    )
                    / 2
                )
                return AgentEvalMetrics(
                    json_schema_pass_rate=schema_passes,
                    memory_persistence_rate=float(memory_ok),
                    groundedness_rate=grounded,
                    hydration_trigger_accuracy=hydration_accuracy,
                )
            finally:
                await session.rollback()
                await _cleanup(session, repo_names, session_key)
    finally:
        if isinstance(llm_client, FallbackLLMRouter):
            await llm_client.aclose()
        await engine.dispose()


async def _schema_pass_rate(llm_client: StructuredLLMClient) -> float:
    prompts = (
        "Find Python GSoC issues and avoid documentation.",
        "Show me Rust parser bugs.",
        "Remember that I prefer beginner issues.",
        "Dismiss issue #17 because it is not relevant.",
    )
    passed = 0
    for prompt in prompts:
        plan, _ = await llm_client.complete_structured(
            "Extract a structured intent and preferences.",
            prompt,
            AgentPlan,
        )
        AgentPlan.model_validate_json(plan.model_dump_json())
        passed += 1
    return passed / len(prompts)


async def _seed_memory_benchmark(
    session: AsyncSession,
    full_name: str,
    embedder: DeterministicFakeEmbedder,
) -> None:
    now = datetime.now(UTC)
    owner, name = full_name.split("/", maxsplit=1)
    repository = Repository(
        github_id=_github_id(),
        owner=owner,
        name=name,
        full_name=full_name,
        primary_language="Python",
        topics=["parsing", "education"],
        program_tags=["gsoc"],
        priority=1,
        maintainer_activity_score=0.9,
        last_synced_at=now,
    )
    session.add(repository)
    await session.flush()
    for number, title, labels in (
        (1, "Fix Python parser math bug", ["good first issue"]),
        (2, "Document Python parser behavior", ["documentation"]),
    ):
        body = (
            "This parser issue describes a reproducible behavior and outlines "
            "a practical fix for contributors."
        )
        session.add(
            Issue(
                github_id=_github_id(),
                repo_id=repository.id,
                number=number,
                title=title,
                body=body,
                html_url=f"https://github.com/{full_name}/issues/{number}",
                labels=labels,
                embedding=embedder.embed_query(f"{title} {body}"),
                github_created_at=now - timedelta(days=2),
                github_updated_at=now,
            )
        )
    await session.commit()


def _build_eval_github_client(full_name: str) -> _EvalGitHubClient:
    owner, name = full_name.split("/", maxsplit=1)
    now = datetime.now(UTC)
    batch = FetchedRepoBatch(
        repository=FetchedRepository(
            github_id=_github_id(),
            owner=owner,
            name=name,
            name_with_owner=full_name,
            primary_language="Python",
            topics=["parsing"],
            stars=10,
            is_archived=False,
            last_commit_at=now - timedelta(days=1),
            merged_prs_90d=2,
        ),
        issues=[
            FetchedIssue(
                github_id=_github_id(),
                number=1,
                title="Fix Python parser diagnostics",
                body=(
                    "This open parser issue provides a reproducible example and "
                    "clear steps for contributors to investigate a robust fix."
                ),
                url=f"https://github.com/{full_name}/issues/1",
                state="open",
                created_at=now - timedelta(days=2),
                updated_at=now,
                labels=["good first issue"],
            )
        ],
    )
    return _EvalGitHubClient(batch)


async def _groundedness_rate(
    session: AsyncSession,
    response: ScoutChatResponse,
) -> float:
    matches = response.matches
    if not matches:
        return 1.0
    issue_ids = [match.issue.id for match in matches]
    rows = (
        await session.execute(select(Issue.id, Issue.html_url).where(Issue.id.in_(issue_ids)))
    ).all()
    stored = {issue_id: url for issue_id, url in rows}
    grounded_count = sum(
        1 for match in matches if stored.get(match.issue.id) == match.issue.html_url
    )
    return grounded_count / len(matches)


async def _cleanup(
    session: AsyncSession,
    repository_names: list[str],
    session_key: str,
) -> None:
    await session.execute(delete(Repository).where(Repository.full_name.in_(repository_names)))
    await session.execute(delete(UserProfile).where(UserProfile.session_key == session_key))
    await session.commit()


def _github_id() -> int:
    return int(uuid4().hex[:14], 16)


def _print_metrics(mode: str, metrics: AgentEvalMetrics) -> None:
    print(f"Agent evaluation ({mode})")
    print("| Check | Rate |")
    print("| --- | ---: |")
    print(f"| JSON Schema Pass Rate | {metrics.json_schema_pass_rate:.1%} |")
    print(f"| Multi-Turn Memory Persistence | {metrics.memory_persistence_rate:.1%} |")
    print(f"| Groundedness | {metrics.groundedness_rate:.1%} |")
    print(f"| JIT Hydration Trigger Accuracy | {metrics.hydration_trigger_accuracy:.1%} |")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        metrics = asyncio.run(_run_evaluations(args.mode))
    except Exception as exc:
        print(f"Agent evaluation failed: {exc}", file=sys.stderr)
        return 1
    _print_metrics(args.mode, metrics)
    return 0 if all(value == 1.0 for value in asdict(metrics).values()) else 1


if __name__ == "__main__":
    sys.exit(main())
