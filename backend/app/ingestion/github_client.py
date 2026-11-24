from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.ingestion.seed import RepoTarget

logger = logging.getLogger(__name__)
GRAPHQL_URL = "https://api.github.com/graphql"
USER_AGENT = "Scout-Open-Source-Issue-Matchmaker/0.1"
TRANSIENT_STATUS_CODES = {429, 502, 503, 504}

_REPOSITORY_QUERY = """
query RepositoryIssues(
  $owner: String!, $name: String!, $cursor: String, $issueLimit: Int!
) {
  rateLimit { remaining resetAt cost }
  repository(owner: $owner, name: $name) {
    databaseId
    name
    nameWithOwner
    owner { login }
    primaryLanguage { name }
    repositoryTopics(first: 30) { nodes { topic { name } } }
    stargazerCount
    isArchived
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 1) { nodes { committedDate } }
        }
      }
    }
    pullRequests(
      last: 100, states: [MERGED], orderBy: {field: UPDATED_AT, direction: DESC}
    ) {
      nodes { mergedAt }
    }
    issues(
      first: $issueLimit, after: $cursor,
      orderBy: {field: UPDATED_AT, direction: DESC},
      states: [OPEN, CLOSED]
    ) {
      nodes {
        databaseId
        number
        title
        body
        url
        state
        createdAt
        updatedAt
        labels(first: 20) { nodes { name } }
        assignees(first: 1) { totalCount }
        comments { totalCount }
        timelineItems(
          first: 10, itemTypes: [CROSS_REFERENCED_EVENT, CONNECTED_EVENT]
        ) {
          nodes {
            __typename
            ... on CrossReferencedEvent {
              source { __typename ... on PullRequest { state } }
            }
            ... on ConnectedEvent {
              subject { __typename ... on PullRequest { state } }
            }
          }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""

_ORG_REPOSITORIES_QUERY = """
query ActiveRepositories($org: String!, $limit: Int!) {
  organization(login: $org) {
    repositories(
      first: $limit, isArchived: false,
      orderBy: {field: UPDATED_AT, direction: DESC}
    ) {
      nodes { name owner { login } }
    }
  }
}
"""


class FetchedRepository(BaseModel):
    model_config = ConfigDict(extra="forbid")

    github_id: int
    owner: str
    name: str
    name_with_owner: str
    primary_language: str | None = None
    topics: list[str] = Field(default_factory=list)
    stars: int = 0
    is_archived: bool = False
    last_commit_at: datetime | None = None
    merged_prs_90d: int = 0


class FetchedIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    github_id: int
    number: int
    title: str
    body: str | None = None
    url: str
    state: str
    created_at: datetime
    updated_at: datetime
    labels: list[str] = Field(default_factory=list)
    assignees_count: int = 0
    comments_count: int = 0
    has_linked_pr: bool = False


class RateLimitInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    remaining: int
    reset_at: datetime
    cost: int


class FetchedRepoBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: FetchedRepository
    issues: list[FetchedIssue]
    rate_limit: RateLimitInfo | None = None


class GitHubGraphQLError(RuntimeError):
    """Raised when GitHub returns a GraphQL error or missing repository."""


class GitHubGraphQLClient:
    def __init__(
        self,
        token: str,
        *,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
        retry_base_seconds: float = 0.25,
    ) -> None:
        if not token:
            raise ValueError("GITHUB_TOKEN is required to run ingestion")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if retry_base_seconds < 0:
            raise ValueError("retry_base_seconds cannot be negative")
        self._token = token
        self._client = (
            client
            if client is not None
            else httpx.AsyncClient(
                base_url=GRAPHQL_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": USER_AGENT,
                    "Accept": "application/vnd.github+json",
                },
                timeout=httpx.Timeout(30.0),
            )
        )
        self._owns_client = client is None
        self._max_retries = max_retries
        self._retry_base_seconds = retry_base_seconds
        self.rate_limit_remaining: int | None = None

    async def __aenter__(self) -> GitHubGraphQLClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(
        self,
        query: str,
        variables: dict[str, object],
    ) -> dict[str, Any]:
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.post(
                    GRAPHQL_URL,
                    json={"query": query, "variables": variables},
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "User-Agent": USER_AGENT,
                        "Accept": "application/vnd.github+json",
                    },
                )
            except httpx.TransportError:
                if attempt >= self._max_retries:
                    raise
                await asyncio.sleep(self._retry_base_seconds * (2**attempt))
                continue
            if response.status_code in TRANSIENT_STATUS_CODES:
                if attempt >= self._max_retries:
                    response.raise_for_status()
                await asyncio.sleep(self._retry_base_seconds * (2**attempt))
                continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise GitHubGraphQLError("GitHub returned an invalid GraphQL response")
            errors = payload.get("errors")
            if errors:
                raise GitHubGraphQLError(f"GitHub GraphQL request failed: {errors}")
            data = payload.get("data")
            if not isinstance(data, dict):
                raise GitHubGraphQLError("GitHub response did not contain GraphQL data")
            rate_limit = data.get("rateLimit")
            if isinstance(rate_limit, dict):
                remaining = rate_limit.get("remaining")
                self.rate_limit_remaining = remaining if isinstance(remaining, int) else None
            self._log_rate_limit(rate_limit)
            return data
        raise RuntimeError("GitHub request retry loop exited unexpectedly")

    @staticmethod
    def _log_rate_limit(rate_limit: object) -> None:
        if isinstance(rate_limit, dict):
            logger.info(
                "GitHub GraphQL rate limit",
                extra={
                    "remaining": rate_limit.get("remaining"),
                    "reset_at": rate_limit.get("resetAt"),
                    "cost": rate_limit.get("cost"),
                },
            )

    async def fetch_repository_issues(
        self,
        owner: str,
        name: str,
        since: datetime | None = None,
        max_issues: int = 120,
    ) -> FetchedRepoBatch:
        if max_issues < 1:
            raise ValueError("max_issues must be positive")
        issues: list[FetchedIssue] = []
        cursor: str | None = None
        repository: FetchedRepository | None = None
        rate_limit: RateLimitInfo | None = None
        reached_since_cursor = False

        while len(issues) < max_issues and not reached_since_cursor:
            page_size = min(50, max_issues - len(issues))
            data = await self._request(
                _REPOSITORY_QUERY,
                {
                    "owner": owner,
                    "name": name,
                    "cursor": cursor,
                    "issueLimit": page_size,
                },
            )
            repository_data = data.get("repository")
            if repository_data is None:
                raise GitHubGraphQLError(f"Repository not found: {owner}/{name}")
            repository = self._parse_repository(repository_data)
            rate_limit_data = data.get("rateLimit")
            if isinstance(rate_limit_data, dict):
                rate_limit = RateLimitInfo(
                    remaining=rate_limit_data["remaining"],
                    reset_at=datetime.fromisoformat(
                        rate_limit_data["resetAt"].replace("Z", "+00:00")
                    ),
                    cost=rate_limit_data["cost"],
                )
            issue_connection = repository_data.get("issues") or {}
            for issue_data in issue_connection.get("nodes") or []:
                issue = self._parse_issue(issue_data)
                if since is not None and _as_utc(issue.updated_at) <= _as_utc(since):
                    reached_since_cursor = True
                    break
                issues.append(issue)
                if len(issues) >= max_issues:
                    break
            page_info = issue_connection.get("pageInfo") or {}
            if (
                reached_since_cursor
                or len(issues) >= max_issues
                or not page_info.get("hasNextPage")
            ):
                break
            cursor = page_info.get("endCursor")
            if not cursor:
                raise GitHubGraphQLError("GitHub pagination omitted endCursor")

        if repository is None:
            raise GitHubGraphQLError(f"Repository not found: {owner}/{name}")
        return FetchedRepoBatch(
            repository=repository,
            issues=issues,
            rate_limit=rate_limit,
        )

    async def fetch_org_active_repos(self, org: str, limit: int = 10) -> list[RepoTarget]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        data = await self._request(_ORG_REPOSITORIES_QUERY, {"org": org, "limit": limit})
        organization = data.get("organization")
        if organization is None:
            raise GitHubGraphQLError(f"Organization not found: {org}")
        return [
            RepoTarget(owner=node["owner"]["login"], name=node["name"])
            for node in organization["repositories"]["nodes"]
        ]

    @staticmethod
    def _parse_repository(data: dict[str, Any]) -> FetchedRepository:
        history = (
            (data.get("defaultBranchRef") or {})
            .get("target", {})
            .get("history", {})
            .get("nodes", [])
        )
        last_commit_at = history[0]["committedDate"] if history else None
        merged_at_values = [
            node.get("mergedAt")
            for node in (data.get("pullRequests") or {}).get("nodes", [])
            if node.get("mergedAt")
        ]
        cutoff = datetime.now(UTC) - timedelta(days=90)
        merged_prs_90d = sum(1 for value in merged_at_values if _as_utc(value) >= cutoff)
        return FetchedRepository(
            github_id=data["databaseId"],
            owner=data["owner"]["login"],
            name=data["name"],
            name_with_owner=data["nameWithOwner"],
            primary_language=(data.get("primaryLanguage") or {}).get("name"),
            topics=[
                item["topic"]["name"]
                for item in (data.get("repositoryTopics") or {}).get("nodes", [])
            ],
            stars=data.get("stargazerCount", 0),
            is_archived=data.get("isArchived", False),
            last_commit_at=last_commit_at,
            merged_prs_90d=merged_prs_90d,
        )

    @staticmethod
    def _parse_issue(data: dict[str, Any]) -> FetchedIssue:
        timeline_nodes = (data.get("timelineItems") or {}).get("nodes") or []
        linked_open_pr = False
        for event in timeline_nodes:
            for linked in (event.get("source"), event.get("subject")):
                if (
                    isinstance(linked, dict)
                    and linked.get("__typename") == "PullRequest"
                    and str(linked.get("state", "")).casefold() == "open"
                ):
                    linked_open_pr = True
        return FetchedIssue(
            github_id=data["databaseId"],
            number=data["number"],
            title=data["title"],
            body=data.get("body"),
            url=data["url"],
            state=str(data["state"]).casefold(),
            created_at=data["createdAt"],
            updated_at=data["updatedAt"],
            labels=[
                node["name"]
                for node in (data.get("labels") or {}).get("nodes", [])
                if node.get("name")
            ],
            assignees_count=(data.get("assignees") or {}).get("totalCount", 0),
            comments_count=(data.get("comments") or {}).get("totalCount", 0),
            has_linked_pr=linked_open_pr,
        )


def _as_utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
