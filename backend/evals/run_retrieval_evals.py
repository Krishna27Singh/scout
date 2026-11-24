import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Issue, Repository
from app.db.session import SessionFactory, engine
from app.ingestion.embedder import DeterministicFakeEmbedder, Embedder, FastEmbedder
from app.retrieval.service import HybridRetrievalService
from app.schemas.search import SearchMode, SearchRequest

from .benchmark_dataset import (
    BENCHMARK_ISSUES,
    BENCHMARK_REPOSITORIES,
    EVAL_CASES,
    BenchmarkIssue,
    issue_updated_at,
)
from .metrics import negative_constraint_violations, recall_at_k, reciprocal_rank

MODES: tuple[SearchMode, ...] = ("vector_only", "fts_only", "hybrid_rerank")
EVAL_REPO_GITHUB_ID_START = -3_000_000
EVAL_ISSUE_GITHUB_ID_START = -4_000_000


@dataclass(frozen=True)
class ModeMetrics:
    mode: SearchMode
    recall_at_5: float
    recall_at_10: float
    mrr: float
    violation_rate: float
    p50_latency_ms: float


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate Scout retrieval quality")
    parser.add_argument(
        "--embedder",
        choices=("fastembed", "fake"),
        default="fastembed",
    )
    parser.add_argument("--output-json", type=Path)
    return parser


def _create_embedder(kind: str) -> Embedder:
    if kind == "fake":
        return DeterministicFakeEmbedder()
    return FastEmbedder()


def _embedding_text(issue: BenchmarkIssue) -> str:
    repository = next(
        item for item in BENCHMARK_REPOSITORIES if item.full_name == issue.repo_full_name
    )
    return " ".join(
        (
            f"Repository: {repository.full_name}",
            f"Language: {repository.language}",
            f"Topics: {' '.join(repository.topics)}",
            f"Issue labels: {' '.join(issue.labels)}",
            f"Issue title: {issue.title}",
            f"Issue body: {issue.body}",
        )
    )


async def _seed_benchmark(
    session: AsyncSession,
    embedder: Embedder,
    now: datetime,
) -> None:
    vectors = embedder.embed_documents([_embedding_text(issue) for issue in BENCHMARK_ISSUES])
    if len(vectors) != len(BENCHMARK_ISSUES):
        raise ValueError("Embedder returned an unexpected number of benchmark vectors")

    repository_ids: dict[str, int] = {}
    for index, repo in enumerate(BENCHMARK_REPOSITORIES):
        values = {
            "github_id": EVAL_REPO_GITHUB_ID_START - index,
            "owner": repo.owner,
            "name": repo.name,
            "full_name": repo.full_name,
            "primary_language": repo.language,
            "topics": list(repo.topics),
            "stars": 1000,
            "is_archived": False,
            "maintainer_activity_score": repo.maintainer_activity_score,
            "source": "curated",
            "program_tags": list(repo.program_tags),
            "priority": 1 if "gsoc" in repo.program_tags else 10,
        }
        statement = insert(Repository).values(**values)
        repository_id = await session.scalar(
            statement.on_conflict_do_update(
                index_elements=[Repository.full_name],
                set_={
                    key: value
                    for key, value in values.items()
                    if key not in {"github_id", "full_name"}
                },
            ).returning(Repository.id)
        )
        if repository_id is None:
            raise RuntimeError(f"Unable to seed evaluation repository {repo.full_name}")
        repository_ids[repo.full_name] = repository_id

    issue_values = []
    for index, (issue, vector) in enumerate(zip(BENCHMARK_ISSUES, vectors, strict=True)):
        issue_values.append(
            {
                "github_id": EVAL_ISSUE_GITHUB_ID_START - index,
                "repo_id": repository_ids[issue.repo_full_name],
                "number": issue.number,
                "title": issue.title,
                "body": issue.body,
                "html_url": (f"https://github.com/{issue.repo_full_name}/issues/{issue.number}"),
                "state": "open",
                "labels": list(issue.labels),
                "comments_count": issue.comments_count,
                "is_actionable": True,
                "embedding": vector,
                "github_created_at": issue_updated_at(issue, now),
                "github_updated_at": issue_updated_at(issue, now),
                "updated_at": issue_updated_at(issue, now),
            }
        )
    issue_insert = insert(Issue).values(issue_values)
    await session.execute(
        issue_insert.on_conflict_do_update(
            index_elements=[Issue.github_id],
            set_={
                "repo_id": issue_insert.excluded.repo_id,
                "number": issue_insert.excluded.number,
                "title": issue_insert.excluded.title,
                "body": issue_insert.excluded.body,
                "html_url": issue_insert.excluded.html_url,
                "state": issue_insert.excluded.state,
                "labels": issue_insert.excluded.labels,
                "comments_count": issue_insert.excluded.comments_count,
                "is_actionable": issue_insert.excluded.is_actionable,
                "embedding": issue_insert.excluded.embedding,
                "github_created_at": issue_insert.excluded.github_created_at,
                "github_updated_at": issue_insert.excluded.github_updated_at,
                "updated_at": issue_insert.excluded.updated_at,
            },
        )
    )


async def _evaluate_mode(
    session: AsyncSession,
    service: HybridRetrievalService,
    mode: SearchMode,
) -> ModeMetrics:
    recall_5: list[float] = []
    recall_10: list[float] = []
    reciprocal_ranks: list[float] = []
    latencies: list[float] = []
    violations = 0
    result_count = 0
    for case in EVAL_CASES:
        response = await service.search(
            session,
            SearchRequest(
                query=case.query,
                filters=case.filters,
                limit=10,
                mode=mode,
            ),
        )
        retrieved = response.results
        recall_5.append(recall_at_k(retrieved, case.relevant_keys, 5))
        recall_10.append(recall_at_k(retrieved, case.relevant_keys, 10))
        reciprocal_ranks.append(reciprocal_rank(retrieved, case.relevant_keys))
        violations += round(
            negative_constraint_violations(retrieved, case.filters) * len(retrieved)
        )
        result_count += len(retrieved)
        latencies.append(response.latency_ms)
    return ModeMetrics(
        mode=mode,
        recall_at_5=sum(recall_5) / len(recall_5),
        recall_at_10=sum(recall_10) / len(recall_10),
        mrr=sum(reciprocal_ranks) / len(reciprocal_ranks),
        violation_rate=violations / result_count if result_count else 0.0,
        p50_latency_ms=median(latencies),
    )


async def _run_evaluations(embedder_name: str) -> list[ModeMetrics]:
    embedder = _create_embedder(embedder_name)
    service = HybridRetrievalService(embedder)
    now = datetime.now(UTC)
    async with SessionFactory() as session:
        try:
            await _seed_benchmark(session, embedder, now)
            metrics: list[ModeMetrics] = []
            for mode in MODES:
                metrics.append(await _evaluate_mode(session, service, mode))
            return metrics
        finally:
            await session.rollback()


def _markdown_table(metrics: Sequence[ModeMetrics]) -> str:
    lines = [
        "| Mode | Recall@5 | Recall@10 | MRR | Violations | p50 ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in metrics:
        lines.append(
            f"| {item.mode} | {item.recall_at_5:.3f} | {item.recall_at_10:.3f} "
            f"| {item.mrr:.3f} | {item.violation_rate:.3%} | {item.p50_latency_ms:.1f} |"
        )
    return "\n".join(lines)


async def _run_and_dispose(embedder_name: str) -> list[ModeMetrics]:
    try:
        return await _run_evaluations(embedder_name)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        metrics = asyncio.run(_run_and_dispose(args.embedder))
    except Exception as exc:
        print(f"Retrieval evaluation failed: {exc}", file=sys.stderr)
        return 1

    print(_markdown_table(metrics))
    if args.output_json is not None:
        payload = {
            "embedder": args.embedder,
            "metrics": [asdict(item) for item in metrics],
            "queries": len(EVAL_CASES),
        }
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    hybrid = next(item for item in metrics if item.mode == "hybrid_rerank")
    if hybrid.violation_rate > 0:
        return 1
    if args.embedder == "fastembed" and (hybrid.recall_at_5 < 0.70 or hybrid.mrr < 0.70):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
