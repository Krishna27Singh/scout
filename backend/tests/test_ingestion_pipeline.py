import math
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.ingestion import cli as cli_module
from app.ingestion.cli import build_parser
from app.ingestion.embedder import DeterministicFakeEmbedder
from app.ingestion.github_client import FetchedRepoBatch, FetchedRepository
from app.ingestion.pipeline import (
    IngestionPipeline,
    RepoSyncStats,
    resolve_seed_targets,
)
from app.ingestion.seed import (
    RepoTarget,
    load_seed_catalog,
    load_seed_repos,
    merge_repo_targets,
)


def test_fake_embedder_is_deterministic_and_unit_norm() -> None:
    embedder = DeterministicFakeEmbedder()
    vector = embedder.embed_query("same input")

    assert vector == embedder.embed_query("same input")
    assert vector != embedder.embed_query("different input")
    assert len(vector) == 384
    assert math.sqrt(sum(value * value for value in vector)) == pytest.approx(1.0)
    assert embedder.embed_documents([]) == []


def test_seed_file_has_gsoc_catalog_and_ecosystem_targets() -> None:
    catalog = load_seed_catalog(Path(__file__).parents[1] / "app" / "ingestion" / "repos.yaml")

    gsoc_repos = [repo for repo in catalog.repositories if "gsoc" in repo.program_tags]
    gsoc_orgs = [org for org in catalog.organizations if "gsoc" in org.program_tags]
    assert len(gsoc_repos) >= 50
    assert len(gsoc_orgs) >= 15
    assert "fastapi/fastapi" in {repo.full_name for repo in catalog.repositories}
    assert all(repo.priority == 1 for repo in gsoc_repos)
    assert all(org.max_repos == 2 and org.priority == 2 for org in gsoc_orgs)


def test_seed_loader_keeps_explicit_repository_compatibility() -> None:
    repos = load_seed_repos(Path(__file__).parents[1] / "app" / "ingestion" / "repos.yaml")

    assert len(repos) >= 60


def test_duplicate_targets_merge_tags_and_keep_highest_priority() -> None:
    merged = merge_repo_targets(
        [
            RepoTarget(
                owner="Acme",
                name="Project",
                priority=10,
                program_tags=["ecosystem"],
            ),
            RepoTarget(
                owner="acme",
                name="project",
                priority=2,
                program_tags=["gsoc", "Ecosystem"],
            ),
        ]
    )

    assert len(merged) == 1
    assert merged[0].priority == 2
    assert merged[0].program_tags == ["ecosystem", "gsoc"]


class DiscoveryClient:
    def __init__(
        self,
        discovered: dict[str, list[RepoTarget]] | None = None,
        remaining: int | None = 10_000,
    ) -> None:
        self.discovered = discovered or {}
        self.rate_limit_remaining = remaining
        self.discovered_orgs: list[str] = []

    async def fetch_repository_issues(
        self,
        owner: str,
        name: str,
        since: datetime | None = None,
        max_issues: int = 120,
    ) -> FetchedRepoBatch:
        raise AssertionError(
            f"Unexpected issue fetch for {owner}/{name}; cursor={since}, limit={max_issues}"
        )

    async def fetch_org_active_repos(self, org: str, limit: int = 10) -> list[RepoTarget]:
        self.discovered_orgs.append(org)
        return self.discovered.get(org, [])[:limit]


async def test_resolution_filters_program_and_deduplicates_org_repositories(
    tmp_path: Path,
) -> None:
    seed_file = tmp_path / "repos.yaml"
    seed_file.write_text(
        """repositories:
  - owner: acme
    name: shared
    priority: 10
    program_tags: [ecosystem]
  - owner: acme
    name: general
    priority: 10
    program_tags: [ecosystem]
organizations:
  - org: acme
    max_repos: 2
    priority: 2
    program_tags: [gsoc]
""",
        encoding="utf-8",
    )
    client = DiscoveryClient(
        {
            "acme": [
                RepoTarget(owner="ACME", name="SHARED"),
                RepoTarget(owner="acme", name="gsoc-project"),
            ]
        }
    )

    targets = await resolve_seed_targets(load_seed_catalog(seed_file), client, program=" GSoC ")

    assert [target.full_name for target in targets] == [
        "acme/gsoc-project",
        "ACME/SHARED",
    ]
    assert all(target.priority == 2 for target in targets)
    assert all(target.program_tags == ["gsoc"] for target in targets)
    assert client.discovered_orgs == ["acme"]
    client.discovered_orgs.clear()

    limited_targets = await resolve_seed_targets(
        load_seed_catalog(seed_file), client, program="gsoc", max_repos=1
    )

    assert [target.full_name for target in limited_targets] == ["acme/gsoc-project"]


async def test_sync_seed_repos_processes_priority_then_owner_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_file = tmp_path / "repos.yaml"
    seed_file.write_text(
        """repositories:
  - owner: zzz
    name: general
    priority: 10
    program_tags: [ecosystem]
  - owner: gsoc
    name: second
    priority: 1
    program_tags: [gsoc]
  - owner: gsoc
    name: first
    priority: 1
    program_tags: [gsoc]
organizations: []
""",
        encoding="utf-8",
    )
    client = DiscoveryClient()
    pipeline = IngestionPipeline(client, embedder=DeterministicFakeEmbedder())
    processed: list[tuple[str, int, list[str], str, int | None, bool]] = []
    received_full: list[bool] = []

    async def fake_sync(
        session: object,
        owner: str,
        name: str,
        source: str = "curated",
        max_issues: int | None = None,
        priority: int = 100,
        program_tags: list[str] | None = None,
        full: bool = False,
    ) -> RepoSyncStats:
        received_full.append(full)
        processed.append(
            (
                f"{owner}/{name}",
                priority,
                program_tags or [],
                source,
                max_issues,
                session is None,
            )
        )
        return RepoSyncStats(f"{owner}/{name}", 1, 1, 1, 0, 0)

    monkeypatch.setattr(pipeline, "sync_repository", fake_sync)
    summary = await pipeline.sync_seed_repos(None, seed_file, program="gsoc", full=True)

    assert processed == [
        ("gsoc/first", 1, ["gsoc"], "curated", None, True),
        ("gsoc/second", 1, ["gsoc"], "curated", None, True),
    ]
    assert received_full == [True, True]
    assert summary.synced == 2
    assert summary.failed == 0


async def test_sync_seed_repos_stops_between_repositories_at_low_rate_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_file = tmp_path / "repos.yaml"
    seed_file.write_text(
        """repositories:
  - owner: first
    name: project
    priority: 1
    program_tags: [gsoc]
  - owner: second
    name: project
    priority: 2
    program_tags: [gsoc]
organizations: []
""",
        encoding="utf-8",
    )
    client = DiscoveryClient(remaining=1000)
    pipeline = IngestionPipeline(client, embedder=DeterministicFakeEmbedder())
    processed: list[tuple[str, int, list[str], str, int | None, bool]] = []

    async def fake_sync(
        session: object,
        owner: str,
        name: str,
        source: str = "curated",
        max_issues: int | None = None,
        priority: int = 100,
        program_tags: list[str] | None = None,
        full: bool = False,
    ) -> RepoSyncStats:
        del full
        processed.append(
            (
                f"{owner}/{name}",
                priority,
                program_tags or [],
                source,
                max_issues,
                session is None,
            )
        )
        client.rate_limit_remaining = 199
        return RepoSyncStats(f"{owner}/{name}", 1, 1, 1, 0, 0)

    monkeypatch.setattr(pipeline, "sync_repository", fake_sync)
    summary = await pipeline.sync_seed_repos(None, seed_file)

    assert processed == [("first/project", 1, ["gsoc"], "curated", None, True)]
    assert summary.synced == 1
    assert summary.stopped_for_rate_limit is True


def test_cli_argument_parsing_for_sync_and_prune() -> None:
    parser = build_parser()

    sync_args = parser.parse_args(
        [
            "sync",
            "--repo",
            "fastapi/fastapi",
            "--max-issues",
            "30",
            "--program",
            "gsoc",
            "--max-repos",
            "4",
            "--full",
        ]
    )
    default_sync_args = parser.parse_args(["sync"])
    prune_args = parser.parse_args(["prune", "--closed-days", "20"])

    assert sync_args.command == "sync"
    assert sync_args.repo == "fastapi/fastapi"
    assert sync_args.max_issues == 30
    assert sync_args.program == "gsoc"
    assert sync_args.max_repos == 4
    assert sync_args.full is True
    assert default_sync_args.full is False
    assert prune_args.command == "prune"
    assert prune_args.closed_days == 20


def test_cli_rejects_non_positive_max_issue_count() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["sync", "--max-issues", "0"])


@pytest.mark.parametrize(
    ("full", "expected_since"),
    [
        (True, None),
        (False, datetime(2026, 11, 24, tzinfo=UTC)),
    ],
)
async def test_full_sync_ignores_saved_last_synced_at(
    full: bool,
    expected_since: datetime | None,
) -> None:
    saved_sync_time = datetime(2026, 11, 24, tzinfo=UTC)

    class CapturingClient:
        since: datetime | None = None

        async def fetch_repository_issues(
            self,
            owner: str,
            name: str,
            since: datetime | None = None,
            max_issues: int = 120,
        ) -> FetchedRepoBatch:
            del owner, name, max_issues
            self.since = since
            return FetchedRepoBatch(
                repository=FetchedRepository(
                    github_id=1,
                    owner="acme",
                    name="project",
                    name_with_owner="acme/project",
                    primary_language="Python",
                    topics=[],
                    stars=10,
                    is_archived=False,
                    last_commit_at=None,
                    merged_prs_90d=0,
                ),
                issues=[],
            )

        async def fetch_org_active_repos(self, org: str, limit: int = 10) -> list[RepoTarget]:
            del org, limit
            return []

    client = CapturingClient()
    session = AsyncMock()
    session.scalar.side_effect = [
        SimpleNamespace(last_synced_at=saved_sync_time),
        1,
    ]
    pipeline = IngestionPipeline(client, embedder=DeterministicFakeEmbedder())

    await pipeline.sync_repository(session, "acme", "project", full=full)

    assert client.since == expected_since


async def test_single_repo_cli_sync_inherits_seed_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: object) -> None:
            del args

    class GitHubContext:
        def __init__(self, token: str) -> None:
            assert token == "test-token"

        async def __aenter__(self) -> "GitHubContext":
            return self

        async def __aexit__(self, *args: object) -> None:
            del args

    class CapturingPipeline:
        def __init__(self, github_client: object, settings: Settings) -> None:
            del github_client, settings

        async def sync_repository(
            self,
            session: object,
            owner: str,
            name: str,
            **kwargs: object,
        ) -> RepoSyncStats:
            del session, owner, name
            captured.update(kwargs)
            return RepoSyncStats("sympy/sympy", 0, 0, 0, 0, 0)

    monkeypatch.setattr(
        cli_module,
        "get_settings",
        lambda: Settings(_env_file=None, github_token="test-token"),
    )
    monkeypatch.setattr(cli_module, "SessionFactory", SessionContext)
    monkeypatch.setattr(cli_module, "GitHubGraphQLClient", GitHubContext)
    monkeypatch.setattr(cli_module, "IngestionPipeline", CapturingPipeline)

    args = build_parser().parse_args(["sync", "--repo", "SymPy/SymPy"])
    await cli_module._run(args)

    assert captured["program_tags"] == ["gsoc"]
    assert captured["priority"] == 1
