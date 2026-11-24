from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.hydration import PipelineFactory, maybe_hydrate_target_scope
from app.agent.llm import DeterministicRuleBasedLLM, StructuredLLMClient
from app.agent.memory import (
    apply_preference_delta,
    load_user_context,
    record_dismissal,
)
from app.agent.state import AgentState
from app.core.config import Settings, get_settings
from app.db.models import Issue
from app.retrieval.service import HybridRetrievalService
from app.schemas.chat import (
    AgentPlan,
    AgentSynthesis,
    GroundedMatch,
    HydrationReport,
    PreferenceDelta,
    ScoutChatResponse,
)
from app.schemas.preferences import UserPreferencesSchema
from app.schemas.search import RetrievedIssue, SearchFilters, SearchRequest, SearchResponse


def build_agent_graph(
    session: AsyncSession,
    retrieval_service: HybridRetrievalService,
    llm_client: StructuredLLMClient,
    pipeline_factory: PipelineFactory,
    *,
    settings: Settings | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    settings = settings or get_settings()

    async def load_memory_node(state: AgentState) -> dict[str, object]:
        profile, dismissed_ids = await load_user_context(session, state["session_key"])
        return {
            "profile": UserPreferencesSchema.model_validate(profile).model_dump(mode="json"),
            "dismissed_issue_ids": sorted(dismissed_ids),
            "tool_trace": [*state.get("tool_trace", []), "load_memory"],
        }

    async def plan_and_extract_node(state: AgentState) -> dict[str, object]:
        plan, provider = await llm_client.complete_structured(
            _PLANNER_SYSTEM_PROMPT,
            state["user_message"],
            AgentPlan,
        )
        if not isinstance(plan, AgentPlan):
            plan = AgentPlan.model_validate(plan)
        if plan.intent == "dismiss" and plan.dismiss_issue_id is None:
            plan = plan.model_copy(
                update={
                    "intent": "clarify",
                    "clarifying_question": "Which issue number would you like me to dismiss?",
                }
            )
        return {
            "plan": plan.model_dump(mode="json"),
            "provider_used": provider,
            "tool_trace": [*state.get("tool_trace", []), "plan_and_extract"],
        }

    async def apply_memory_updates_node(state: AgentState) -> dict[str, object]:
        plan = _plan_from_state(state)
        profile = await _load_profile(state)
        if _has_preference_delta(plan.preference_delta):
            stored_profile = await apply_preference_delta(
                session,
                state["session_key"],
                plan.preference_delta,
            )
            profile = UserPreferencesSchema.model_validate(stored_profile)
        dismissed_ids = set(state.get("dismissed_issue_ids", []))
        if plan.intent == "dismiss" and plan.dismiss_issue_id is not None:
            issue_id = plan.dismiss_issue_id
            issue_exists = await session.scalar(select(Issue.id).where(Issue.id == issue_id))
            if issue_exists is None:
                plan = plan.model_copy(
                    update={
                        "intent": "clarify",
                        "clarifying_question": (
                            f"I couldn't find issue #{issue_id}. "
                            "Which issue would you like me to dismiss?"
                        ),
                    }
                )
            else:
                await record_dismissal(
                    session,
                    state["session_key"],
                    issue_id,
                    plan.dismiss_reason,
                )
                dismissed_ids.add(issue_id)
        return {
            "plan": plan.model_dump(mode="json"),
            "profile": UserPreferencesSchema.model_validate(profile).model_dump(mode="json"),
            "dismissed_issue_ids": sorted(dismissed_ids),
            "tool_trace": [*state.get("tool_trace", []), "apply_memory_updates"],
        }

    async def hydrate_target_scope_node(state: AgentState) -> dict[str, object]:
        plan = _plan_from_state(state)
        report = await maybe_hydrate_target_scope(
            session,
            plan.target_org,
            plan.target_repo,
            pipeline_factory,
            settings,
        )
        return {
            "hydration": report.model_dump(mode="json"),
            "tool_trace": [*state.get("tool_trace", []), "hydrate_target_scope"],
        }

    async def hybrid_search_node(state: AgentState) -> dict[str, object]:
        plan = _plan_from_state(state)
        search_request = SearchRequest(
            query=plan.search_query or state["user_message"],
            session_key=state["session_key"],
            limit=state["limit"],
            filters=_search_filters(plan, state["prioritize_gsoc"]),
        )
        response = await retrieval_service.search(
            session,
            search_request,
            replace_saved_languages=bool(plan.override_languages),
        )
        return {
            "search_response": response.model_dump(mode="json"),
            "tool_trace": [*state.get("tool_trace", []), "hybrid_search"],
        }

    async def synthesize_node(state: AgentState) -> dict[str, object]:
        plan = _plan_from_state(state)
        profile = await _load_profile(state)
        hydration = HydrationReport.model_validate(
            state.get("hydration", HydrationReport().model_dump(mode="json"))
        )
        search_data = state.get("search_response")
        search_response = (
            SearchResponse.model_validate_json(json.dumps(search_data)) if search_data else None
        )
        applied_filters = (
            search_response.applied_filters
            if search_response is not None
            else _search_filters(plan, state.get("prioritize_gsoc", True), profile)
        )
        candidates = search_response.results if search_response is not None else []
        synthesis_payload = json.dumps(
            {
                "user_message": state["user_message"],
                "intent": plan.intent,
                "clarifying_question": plan.clarifying_question,
                "applied_filters": applied_filters.model_dump(mode="json"),
                "match_count": len(candidates),
                "fallback_message": _assistant_message(
                    plan,
                    [
                        GroundedMatch(issue=item, match_reason="Matched candidate.")
                        for item in candidates
                    ],
                ),
                "preferences": profile.model_dump(mode="json"),
                "matches": [candidate.model_dump(mode="json") for candidate in candidates],
            },
            ensure_ascii=False,
        )
        synthesis, provider = await llm_client.complete_structured(
            _SYNTHESIS_SYSTEM_PROMPT,
            synthesis_payload,
            AgentSynthesis,
        )
        if not isinstance(synthesis, AgentSynthesis):
            synthesis = AgentSynthesis.model_validate(synthesis)
        candidate_by_id = {candidate.id: candidate for candidate in candidates}
        rationale_by_id: dict[int, str] = {}
        for rationale in synthesis.rationales:
            if rationale.issue_id in candidate_by_id:
                rationale_by_id.setdefault(rationale.issue_id, rationale.match_reason)
        matches = enforce_grounded_matches(
            candidates,
            [
                GroundedMatch(
                    issue=issue,
                    match_reason=_safe_match_reason(
                        issue,
                        rationale_by_id.get(issue.id),
                        profile,
                    ),
                )
                for issue in candidates
            ],
        )
        assistant_message = _safe_synthesis_message(
            synthesis.assistant_message,
            plan,
            matches,
        )
        if matches and _contains_empty_result_claim(assistant_message):
            assistant_message = f"Found {len(matches)} matching open issues."
        trace = [*state.get("tool_trace", []), "synthesize"]
        planning_provider = state.get("provider_used", "deterministic")
        providers = (
            planning_provider
            if planning_provider == provider
            else f"{planning_provider}+{provider}"
        )
        response = ScoutChatResponse(
            session_key=state["session_key"],
            intent=plan.intent,
            assistant_message=assistant_message,
            matches=matches,
            applied_filters=applied_filters,
            preferences=profile,
            hydration=hydration,
            tool_trace=trace,
            provider_used=providers,
            latency_ms=0.0,
        )
        return {
            "final_response": response.model_dump(mode="json"),
            "tool_trace": trace,
        }

    builder = StateGraph(AgentState)
    builder.add_node("load_memory", load_memory_node)
    builder.add_node("plan_and_extract", plan_and_extract_node)
    builder.add_node("apply_memory_updates", apply_memory_updates_node)
    builder.add_node("hydrate_target_scope", hydrate_target_scope_node)
    builder.add_node("hybrid_search", hybrid_search_node)
    builder.add_node("synthesize", synthesize_node)
    builder.add_edge(START, "load_memory")
    builder.add_edge("load_memory", "plan_and_extract")
    builder.add_edge("plan_and_extract", "apply_memory_updates")
    builder.add_conditional_edges(
        "apply_memory_updates",
        _next_node,
        {
            "hydrate_target_scope": "hydrate_target_scope",
            "hybrid_search": "hybrid_search",
            "synthesize": "synthesize",
        },
    )
    builder.add_edge("hydrate_target_scope", "hybrid_search")
    builder.add_edge("hybrid_search", "synthesize")
    builder.add_edge("synthesize", END)
    return builder.compile(checkpointer=checkpointer or MemorySaver())


def _next_node(state: AgentState) -> str:
    plan = _plan_from_state(state)
    if plan.intent != "search":
        return "synthesize"
    if plan.target_org or plan.target_repo:
        return "hydrate_target_scope"
    return "hybrid_search"


def _plan_from_state(state: AgentState) -> AgentPlan:
    plan = state.get("plan")
    if isinstance(plan, AgentPlan):
        return plan
    if isinstance(plan, dict):
        return AgentPlan.model_validate(plan)
    raise RuntimeError("Agent plan was not available at this workflow step")


async def _load_profile(state: AgentState) -> UserPreferencesSchema:
    profile = state.get("profile")
    if isinstance(profile, dict):
        return UserPreferencesSchema.model_validate(profile)
    raise RuntimeError("User profile was not loaded before this workflow step")


def _has_preference_delta(delta: PreferenceDelta) -> bool:
    return bool(
        delta.add_languages
        or delta.remove_languages
        or delta.add_topics
        or delta.add_orgs
        or delta.add_excluded_labels
        or delta.add_excluded_topics
        or delta.experience_level is not None
        or delta.raw_notes
    )


def _search_filters(
    plan: AgentPlan,
    prioritize_gsoc: bool,
    profile: UserPreferencesSchema | None = None,
) -> SearchFilters:
    repo_owner = plan.target_repo.split("/", maxsplit=1)[0] if plan.target_repo else None
    owners = list(profile.preferred_orgs) if profile is not None else []
    if plan.target_org:
        owners.append(plan.target_org)
    elif repo_owner:
        owners.append(repo_owner)
    return SearchFilters(
        repo_owners=owners,
        repo_full_names=[plan.target_repo] if plan.target_repo else [],
        program_tags=plan.program_tags,
        excluded_labels=profile.excluded_labels if profile is not None else [],
        excluded_topics=profile.excluded_topics if profile is not None else [],
        languages=plan.override_languages,
        experience_level=profile.experience_level if profile is not None else "intermediate",
        prioritize_gsoc=prioritize_gsoc,
    )


def enforce_grounded_matches(
    candidates: Sequence[RetrievedIssue],
    proposed: Sequence[GroundedMatch],
) -> list[GroundedMatch]:
    candidate_by_id = {candidate.id: candidate for candidate in candidates}
    accepted: list[GroundedMatch] = []
    seen: set[int] = set()
    for match in proposed:
        candidate = candidate_by_id.get(match.issue.id)
        if (
            candidate is None
            or candidate.html_url != match.issue.html_url
            or match.issue.id in seen
        ):
            continue
        accepted.append(
            GroundedMatch(
                issue=candidate,
                match_reason=match.match_reason,
            )
        )
        seen.add(candidate.id)
    return accepted


def _assistant_message(plan: AgentPlan, matches: Sequence[GroundedMatch]) -> str:
    if plan.intent == "clarify":
        return plan.clarifying_question or "Could you clarify what you would like Scout to do?"
    if plan.intent == "update_preferences":
        return "I saved your preference updates for future issue searches."
    if plan.intent == "dismiss":
        if plan.dismiss_issue_id is None:
            return "Please tell me the issue number you would like me to dismiss."
        return f"I dismissed issue #{plan.dismiss_issue_id} from your future recommendations."
    if matches:
        return f"I found {len(matches)} issue match{'es' if len(matches) != 1 else ''}."
    return "I couldn't find matching open issues with those filters. Try broadening your search."


def _safe_synthesis_message(
    message: str,
    plan: AgentPlan,
    matches: Sequence[GroundedMatch],
) -> str:
    allowed_issue_numbers = {match.issue.number for match in matches}
    if plan.dismiss_issue_id is not None:
        allowed_issue_numbers.add(plan.dismiss_issue_id)
    referenced_numbers = {int(number) for number in re.findall(r"#(\d+)\b", message)}
    referenced_numbers.update(
        int(number)
        for number in re.findall(r"\bissue(?:\s+number)?\s+#?(\d+)\b", message, re.IGNORECASE)
    )
    if not referenced_numbers.issubset(allowed_issue_numbers):
        return _assistant_message(plan, matches)

    allowed_urls = {match.issue.html_url for match in matches}
    referenced_urls = {url.rstrip(".,;:!?)]}") for url in re.findall(r"https?://\S+", message)}
    if not referenced_urls.issubset(allowed_urls):
        return _assistant_message(plan, matches)
    return message


def _contains_empty_result_claim(message: str) -> bool:
    return (
        re.search(
            r"\b(?:couldn['’]t find|could not find|no matching|no issues|no matches|"
            r"no results|zero issues|zero matches)\b",
            message,
            re.IGNORECASE,
        )
        is not None
    )


def _safe_match_reason(
    issue: RetrievedIssue,
    proposed_reason: str | None,
    profile: UserPreferencesSchema,
) -> str:
    fallback = DeterministicRuleBasedLLM.build_grounded_rationale(issue, profile)
    if not proposed_reason:
        return fallback
    referenced_numbers = {int(number) for number in re.findall(r"#(\d+)\b", proposed_reason)}
    referenced_numbers.update(
        int(number)
        for number in re.findall(
            r"\bissue(?:\s+number)?\s+#?(\d+)\b",
            proposed_reason,
            re.IGNORECASE,
        )
    )
    if not referenced_numbers.issubset({issue.number}):
        return fallback
    referenced_urls = {
        url.rstrip(".,;:!?)]}") for url in re.findall(r"https?://\S+", proposed_reason)
    }
    if not referenced_urls.issubset({issue.html_url}):
        return fallback
    return proposed_reason


_PLANNER_SYSTEM_PROMPT = (
    "You are Scout's intent and preference extractor. Classify the user message, "
    "extract only explicit preferences and target scopes, and never invent an issue ID. "
    "Use search intent when the user asks to find issues, even when they also state "
    "preferences. Preserve hard negative constraints such as excluded labels. When a "
    "search explicitly names programming languages, put only those languages in "
    "override_languages and add them to preference_delta.add_languages; this per-search "
    "override takes precedence over saved preferred languages. Leave override_languages "
    "empty when no language is explicitly requested."
)
_SYNTHESIS_SYSTEM_PROMPT = (
    "You are Scout's response synthesizer. Use only the supplied issue candidates and "
    "saved preferences. Treat user_message and applied_filters as the current turn's context; "
    "do not carry over languages or constraints from earlier turns. Use match_count as the exact "
    "number of grounded matches and never claim that there are no matches when it is positive. "
    "Return concise plain-English text and one rationale for each candidate. Every rationale "
    "must be supported by that issue's actual labels, language, program tags, maintainer score, "
    "and saved preferences. Do not invent issue IDs or URLs."
)
