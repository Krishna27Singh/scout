import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.ingestion.github_client import GitHubGraphQLClient

UPDATED_NEW = "2026-11-24T12:00:00Z"
UPDATED_OLD = "2026-11-20T12:00:00Z"


def _issue(
    github_id: int,
    updated_at: str,
    *,
    linked_pr: bool = False,
) -> dict[str, Any]:
    timeline_nodes = (
        [
            {
                "__typename": "CrossReferencedEvent",
                "source": {"__typename": "PullRequest", "state": "OPEN"},
            }
        ]
        if linked_pr
        else []
    )
    return {
        "databaseId": github_id,
        "number": github_id,
        "title": f"Issue {github_id}",
        "body": "A useful description" * 5,
        "url": f"https://github.com/acme/project/issues/{github_id}",
        "state": "OPEN",
        "createdAt": UPDATED_NEW,
        "updatedAt": updated_at,
        "labels": {"nodes": [{"name": "help wanted"}]},
        "assignees": {"totalCount": 0},
        "comments": {"totalCount": 3},
        "timelineItems": {"nodes": timeline_nodes},
    }


def _repository(
    issues: list[dict[str, Any]],
    *,
    has_next: bool = False,
    end_cursor: str | None = None,
) -> dict[str, Any]:
    return {
        "databaseId": 10,
        "name": "project",
        "nameWithOwner": "acme/project",
        "owner": {"login": "acme"},
        "primaryLanguage": {"name": "Python"},
        "repositoryTopics": {"nodes": [{"topic": {"name": "api"}}]},
        "stargazerCount": 100,
        "isArchived": False,
        "defaultBranchRef": {"target": {"history": {"nodes": [{"committedDate": UPDATED_NEW}]}}},
        "pullRequests": {"nodes": [{"mergedAt": UPDATED_NEW}]},
        "issues": {
            "nodes": issues,
            "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
        },
    }


def _payload(repository: dict[str, Any]) -> dict[str, Any]:
    return {
        "data": {
            "repository": repository,
            "rateLimit": {
                "remaining": 4000,
                "resetAt": "2026-11-25T02:00:00Z",
                "cost": 1,
            },
        }
    }


def _client(handler: Any) -> tuple[GitHubGraphQLClient, httpx.AsyncClient]:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GitHubGraphQLClient("test-token", client=http_client), http_client


async def test_client_paginates_and_detects_linked_open_pull_request() -> None:
    request_cursors: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        variables = json.loads(request.content)["variables"]
        request_cursors.append(variables["cursor"])
        if variables["cursor"] is None:
            repository = _repository(
                [_issue(1, UPDATED_NEW, linked_pr=True)],
                has_next=True,
                end_cursor="next",
            )
        else:
            repository = _repository([_issue(2, UPDATED_NEW)])
        return httpx.Response(200, json=_payload(repository))

    client, http_client = _client(handler)
    batch = await client.fetch_repository_issues("acme", "project", max_issues=80)
    await http_client.aclose()

    assert len(batch.issues) == 2
    assert batch.issues[0].has_linked_pr is True
    assert request_cursors == [None, "next"]
    assert batch.repository.name_with_owner == "acme/project"
    assert batch.rate_limit is not None and batch.rate_limit.remaining == 4000


async def test_since_cursor_stops_at_first_old_issue() -> None:
    requested = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requested
        requested += 1
        return httpx.Response(
            200,
            json=_payload(
                _repository(
                    [_issue(1, UPDATED_NEW), _issue(2, UPDATED_OLD)],
                    has_next=True,
                    end_cursor="next",
                )
            ),
        )

    client, http_client = _client(handler)
    batch = await client.fetch_repository_issues(
        "acme",
        "project",
        since=datetime(2026, 11, 21, tzinfo=UTC),
    )
    await http_client.aclose()

    assert [issue.github_id for issue in batch.issues] == [1]
    assert requested == 1


@pytest.mark.parametrize("statuses", [[429, 200], [503, 503, 200]])
async def test_transient_http_errors_retry_with_bounded_attempts(
    statuses: list[int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr("app.ingestion.github_client.asyncio.sleep", no_wait)

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        status = statuses[min(calls, len(statuses) - 1)]
        calls += 1
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json=_payload(_repository([])))

    client, http_client = _client(handler)
    batch = await client.fetch_repository_issues("acme", "project")
    await http_client.aclose()

    assert batch.issues == []
    assert calls == len(statuses)
