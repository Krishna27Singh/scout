import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from app.agent import graph as graph_module
from app.agent.graph import _next_node, _safe_match_reason, enforce_grounded_matches
from app.agent.llm import DeterministicRuleBasedLLM
from app.agent.memory import _merge_values
from app.agent.service import ScoutAgentService
from app.core.config import Settings
from app.ingestion.embedder import DeterministicFakeEmbedder
from app.retrieval.service import HybridRetrievalService
from app.schemas.chat import (
    AgentPlan,
    AgentSynthesis,
    ChatRequest,
    GroundedMatch,
    PreferenceDelta,
)
from app.schemas.preferences import UserPreferencesSchema
from app.schemas.search import RetrievedIssue, ScoreBreakdown, SearchFilters, SearchResponse


def _retrieved_issue(
    issue_id: int = 1,
    url: str = "https://github.com/sugarlabs/musicblocks/issues/1",
) -> RetrievedIssue:
    return RetrievedIssue(
        id=issue_id,
        repo_full_name="sugarlabs/musicblocks",
        repo_owner="sugarlabs",
        repo_topics=["education"],
        primary_language="Python",
        program_tags=["gsoc"],
        number=1,
        title="Improve parser diagnostics",
        html_url=url,
        labels=["good first issue"],
        comments_count=2,
        maintainer_activity_score=0.8,
        github_updated_at=datetime.now(UTC),
        snippet="Improve the parser error messages.",
        scores=ScoreBreakdown(
            vector_score=0.8,
            fts_score=0.4,
            rrf_score=0.8,
            maintainer_score=0.8,
            freshness_score=0.9,
            program_boost=1.0,
            experience_boost=0.8,
            final_score=0.8,
        ),
    )


def test_preference_delta_merge_is_idempotent_and_removes_languages_only() -> None:
    merged = _merge_values(
        ["Python", "Rust"],
        ["python", "TypeScript"],
        ["RUST"],
    )
    assert merged == ["python", "typescript"]
    assert _merge_values(merged, ["Python"]) == merged
    assert PreferenceDelta(add_excluded_labels=["Documentation", "docs"]).add_excluded_labels == [
        "documentation",
        "docs",
    ]


async def test_deterministic_planner_extracts_negative_constraints_and_target_scope() -> None:
    plan, provider = await DeterministicRuleBasedLLM().complete_structured(
        "system",
        "Find Python GSoC issues in arxlang/doukimd; avoid documentation and CSS",
        AgentPlan,
    )

    assert provider == "deterministic"
    assert plan.target_org == "arxlang"
    assert plan.target_repo == "arxlang/doukimd"
    assert plan.program_tags == ["gsoc"]
    assert plan.preference_delta.add_excluded_labels == ["css", "documentation"]


async def test_deterministic_planner_extracts_preference_removals() -> None:
    plan, _ = await DeterministicRuleBasedLLM().complete_structured(
        "system",
        "I no longer prefer Python",
        AgentPlan,
    )
    assert plan.intent == "update_preferences"
    assert plan.preference_delta.add_languages == []
    assert plan.preference_delta.remove_languages == ["python"]


async def test_deterministic_synthesis_generates_grounded_rationales() -> None:
    issue = _retrieved_issue()
    payload = json.dumps(
        {
            "intent": "search",
            "preferences": UserPreferencesSchema(preferred_languages=["python"]).model_dump(),
            "matches": [issue.model_dump(mode="json")],
        }
    )
    synthesis, provider = await DeterministicRuleBasedLLM().complete_structured(
        "system",
        payload,
        AgentSynthesis,
    )

    assert provider == "deterministic"
    assert synthesis.rationales[0].issue_id == issue.id
    assert "good first issue" in synthesis.rationales[0].match_reason
    assert "GSoC" in synthesis.rationales[0].match_reason


async def test_compiled_graph_updates_memory_and_records_history(monkeypatch) -> None:
    initial_profile = UserPreferencesSchema()

    async def load_context(session, session_key):
        del session, session_key
        return initial_profile, set()

    async def apply_delta(session, session_key, delta):
        del session, session_key
        return initial_profile.model_copy(update={"experience_level": delta.experience_level})

    monkeypatch.setattr(graph_module, "load_user_context", load_context)
    monkeypatch.setattr(graph_module, "apply_preference_delta", apply_delta)

    def unused_pipeline_factory():
        raise AssertionError("This update-preferences turn must not hydrate.")

    service = ScoutAgentService(
        AsyncMock(),
        HybridRetrievalService(DeterministicFakeEmbedder()),
        DeterministicRuleBasedLLM(),
        unused_pipeline_factory,
        settings=Settings(_env_file=None),
    )
    response = await service.chat(
        ChatRequest(
            session_key="workflow-test",
            message="Remember that I prefer beginner",
        )
    )
    history = await service.get_history("workflow-test")

    assert response.intent == "update_preferences"
    assert response.preferences.experience_level == "beginner"
    assert response.tool_trace == [
        "load_memory",
        "plan_and_extract",
        "apply_memory_updates",
        "synthesize",
    ]
    assert len(history.turns) == 1
    assert history.turns[0].user_message == "Remember that I prefer beginner"


async def test_compiled_graph_search_synthesizes_only_serialized_candidates(monkeypatch) -> None:
    profile = UserPreferencesSchema()

    async def load_context(session, session_key):
        del session, session_key
        return profile, set()

    async def fake_search(session, request):
        del session
        return SearchResponse(
            query=request.query,
            mode="hybrid_rerank",
            applied_filters=SearchFilters(),
            total_candidates=1,
            latency_ms=1.0,
            results=[_retrieved_issue()],
        )

    monkeypatch.setattr(graph_module, "load_user_context", load_context)
    retrieval = HybridRetrievalService(DeterministicFakeEmbedder())
    monkeypatch.setattr(retrieval, "search", fake_search)

    def unused_pipeline_factory():
        raise AssertionError("This general search must not hydrate.")

    service = ScoutAgentService(
        AsyncMock(),
        retrieval,
        DeterministicRuleBasedLLM(),
        unused_pipeline_factory,
        settings=Settings(_env_file=None),
    )
    response = await service.chat(
        ChatRequest(session_key="workflow-search", message="Find parser issues")
    )

    assert response.intent == "search"
    assert len(response.matches) == 1
    assert response.matches[0].issue.id == 1
    assert response.matches[0].issue.html_url.endswith("/issues/1")
    assert "hybrid_search" in response.tool_trace
    assert "good first issue" in response.matches[0].match_reason


def test_langgraph_node_routing_covers_intents_and_target_hydration() -> None:
    for intent in ("update_preferences", "dismiss", "clarify"):
        assert _next_node({"plan": AgentPlan(intent=intent)}) == "synthesize"
    assert _next_node({"plan": AgentPlan(intent="search")}) == "hybrid_search"
    assert (
        _next_node(
            {
                "plan": AgentPlan(intent="search", target_repo="arxlang/doukimd"),
            }
        )
        == "hydrate_target_scope"
    )


def test_grounding_guard_rejects_unknown_ids_and_mismatched_urls() -> None:
    candidate = _retrieved_issue()
    invented = _retrieved_issue(issue_id=999)
    wrong_url = _retrieved_issue(url="https://attacker.invalid/issues/1")

    accepted = enforce_grounded_matches(
        [candidate],
        [
            GroundedMatch(issue=candidate, match_reason="Grounded in its labels."),
            GroundedMatch(issue=invented, match_reason="Invented."),
            GroundedMatch(issue=wrong_url, match_reason="Spoofed URL."),
        ],
    )

    assert len(accepted) == 1
    assert accepted[0].issue.id == candidate.id
    assert accepted[0].issue.html_url == candidate.html_url
    assert _safe_match_reason(
        candidate, "Issue #999 is amazing.", UserPreferencesSchema()
    ) == DeterministicRuleBasedLLM.build_grounded_rationale(
        candidate,
        UserPreferencesSchema(),
    )


def test_deterministic_rationale_uses_real_issue_signals() -> None:
    reason = DeterministicRuleBasedLLM.build_grounded_rationale(
        _retrieved_issue(),
        UserPreferencesSchema(preferred_languages=["python"]),
    )
    assert "preferred Python language" in reason
    assert "GSoC" in reason
    assert "good first issue" in reason
    assert "maintainer activity" in reason
