from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    session_key: str
    user_message: str
    limit: int
    prioritize_gsoc: bool
    conversation_summary: str
    profile: dict[str, object]
    dismissed_issue_ids: list[int]
    plan: dict[str, object]
    hydration: dict[str, object]
    search_response: dict[str, object]
    final_response: dict[str, object]
    tool_trace: list[str]
    provider_used: str
