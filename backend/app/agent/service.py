from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import build_agent_graph
from app.agent.hydration import PipelineFactory
from app.agent.llm import StructuredLLMClient
from app.agent.state import AgentState
from app.core.config import Settings, get_settings
from app.retrieval.service import HybridRetrievalService
from app.schemas.chat import ChatHistoryItem, ChatHistoryResponse, ChatRequest, ScoutChatResponse


class ScoutAgentService:
    def __init__(
        self,
        session: AsyncSession,
        retrieval_service: HybridRetrievalService,
        llm_client: StructuredLLMClient,
        pipeline_factory: PipelineFactory,
        *,
        settings: Settings | None = None,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
    ) -> None:
        self.session = session
        self.checkpointer = checkpointer or MemorySaver()
        self.graph: CompiledStateGraph[AgentState, None, AgentState, AgentState] = (
            build_agent_graph(
                session,
                retrieval_service,
                llm_client,
                pipeline_factory,
                settings=settings or get_settings(),
                checkpointer=self.checkpointer,
            )
        )

    async def chat(self, request: ChatRequest) -> ScoutChatResponse:
        start = time.perf_counter()
        state = await self.graph.ainvoke(
            {
                "session_key": request.session_key,
                "user_message": request.message,
                "limit": request.limit,
                "prioritize_gsoc": request.prioritize_gsoc,
                "conversation_summary": "",
                "profile": {},
                "dismissed_issue_ids": [],
                "hydration": {},
                "search_response": {},
                "final_response": {},
                "tool_trace": [],
                "provider_used": "deterministic",
            },
            config={"configurable": {"thread_id": request.session_key}},
        )
        response_data = state.get("final_response")
        if not isinstance(response_data, dict):
            raise RuntimeError("Agent graph completed without a final response")
        response = ScoutChatResponse.model_validate_json(json.dumps(response_data))
        elapsed_ms = (time.perf_counter() - start) * 1000
        return response.model_copy(update={"latency_ms": elapsed_ms})

    async def get_history(self, session_key: str) -> ChatHistoryResponse:
        history: list[tuple[str, ChatHistoryItem]] = []
        seen_checkpoints: set[str] = set()
        snapshots: AsyncIterator[object] = self.graph.aget_state_history(
            {"configurable": {"thread_id": session_key}}
        )
        async for snapshot in snapshots:
            snapshot_values = getattr(snapshot, "values", {})
            snapshot_next = getattr(snapshot, "next", ("unknown",))
            if snapshot_next or not isinstance(snapshot_values, dict):
                continue
            final_data = snapshot_values.get("final_response")
            user_message = snapshot_values.get("user_message")
            if (
                not isinstance(final_data, dict)
                or not final_data
                or not isinstance(user_message, str)
            ):
                continue
            snapshot_config = getattr(snapshot, "config", None)
            if not isinstance(snapshot_config, dict):
                continue
            configurable = snapshot_config.get("configurable", {})
            if not isinstance(configurable, dict):
                configurable = {}
            checkpoint_id = configurable.get("checkpoint_id")
            unique_key = str(
                checkpoint_id or f"{user_message}:{final_data.get('assistant_message')}"
            )
            if unique_key in seen_checkpoints:
                continue
            seen_checkpoints.add(unique_key)
            response = ScoutChatResponse.model_validate_json(json.dumps(final_data))
            created_at = str(getattr(snapshot, "created_at", "") or "")
            history.append(
                (
                    created_at,
                    ChatHistoryItem(
                        user_message=user_message,
                        assistant_message=response.assistant_message,
                        intent=response.intent,
                    ),
                )
            )
        history.sort(key=lambda item: item[0])
        return ChatHistoryResponse(
            session_key=session_key,
            turns=[turn for _, turn in history],
        )
