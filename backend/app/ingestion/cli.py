import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from app.core.config import get_settings
from app.db.session import SessionFactory, engine
from app.ingestion.github_client import GitHubGraphQLClient
from app.ingestion.pipeline import IngestionPipeline, find_seed_repo_target
from app.ingestion.seed import RepoTarget

DEFAULT_REPOS_FILE = Path(__file__).with_name("repos.yaml")


def _positive_integer(value: str) -> int:
    try:
        integer = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if integer < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return integer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scout GitHub issue ingestion")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync", help="Sync curated or one repository")
    sync_parser.add_argument("--repos-file", type=Path, default=DEFAULT_REPOS_FILE)
    sync_parser.add_argument("--repo", help="Only sync one repository in owner/name form")
    sync_parser.add_argument("--max-issues", type=_positive_integer)
    sync_parser.add_argument(
        "--full",
        action="store_true",
        help="Ignore the last-sync cursor and backfill open issues",
    )
    sync_parser.add_argument(
        "--program",
        help="Only sync seed targets tagged with this program (for example: gsoc)",
    )
    sync_parser.add_argument(
        "--max-repos",
        type=_positive_integer,
        help="Cap the number of sorted seed targets to sync",
    )

    prune_parser = subparsers.add_parser("prune", help="Prune expired issues and repositories")
    prune_parser.add_argument("--closed-days", type=_positive_integer)
    prune_parser.add_argument("--on-demand-days", type=_positive_integer)
    return parser


async def _run(args: argparse.Namespace) -> tuple[dict[str, object], bool]:
    settings = get_settings()
    async with SessionFactory() as session:
        if args.command == "prune":
            pipeline = IngestionPipeline(None, settings=settings)
            prune_stats = await pipeline.prune_stale_data(
                session,
                closed_days=(
                    args.closed_days
                    if args.closed_days is not None
                    else settings.closed_issue_retention_days
                ),
                on_demand_days=(
                    args.on_demand_days
                    if args.on_demand_days is not None
                    else settings.on_demand_repo_retention_days
                ),
            )
            return asdict(prune_stats), False

        async with GitHubGraphQLClient(settings.github_token) as github_client:
            pipeline = IngestionPipeline(github_client, settings=settings)
            if args.repo:
                try:
                    target = _parse_target(args.repo)
                    seed_target = find_seed_repo_target(
                        args.repos_file,
                        target.owner,
                        target.name,
                    )
                    stats = await pipeline.sync_repository(
                        session,
                        target.owner,
                        target.name,
                        max_issues=args.max_issues,
                        priority=seed_target.priority if seed_target is not None else 100,
                        program_tags=seed_target.program_tags if seed_target is not None else None,
                        full=args.full,
                    )
                except Exception as exc:
                    await session.rollback()
                    return {"synced": 0, "failed": 1, "errors": {args.repo: str(exc)}}, True
                return {"synced": 1, "failed": 0, **asdict(stats)}, False

            summary = await pipeline.sync_seed_repos(
                session,
                args.repos_file,
                max_issues_per_repo=args.max_issues,
                program=args.program,
                max_repos=args.max_repos,
                full=args.full,
            )
            return asdict(summary), summary.synced == 0 and summary.failed > 0


async def _run_and_dispose(args: argparse.Namespace) -> tuple[dict[str, object], bool]:
    try:
        return await _run(args)
    finally:
        await engine.dispose()


def _parse_target(value: str) -> RepoTarget:
    parts = value.split("/")
    if len(parts) != 2:
        raise ValueError("Repository must be specified as owner/name")
    return RepoTarget(owner=parts[0], name=parts[1])


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary, all_failed = asyncio.run(_run_and_dispose(args))
    except Exception as exc:
        print(
            json.dumps({"failed": 1, "error": str(exc)}, indent=2, sort_keys=True),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if all_failed else 0


if __name__ == "__main__":
    sys.exit(main())
