import json

import httpx
import pytest

from app.agent.llm import (
    DeterministicRuleBasedLLM,
    FallbackLLMRouter,
    OpenAICompatLLMClient,
)
from app.core.config import Settings
from app.schemas.chat import AgentPlan


def _completion(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}]},
    )


def _plan_json() -> str:
    return json.dumps(
        {
            "intent": "search",
            "search_query": "Python GSoC issues",
            "preference_delta": {
                "add_languages": ["python"],
                "add_excluded_labels": ["documentation"],
            },
            "target_org": "sugarlabs",
            "target_repo": None,
            "program_tags": ["gsoc"],
            "dismiss_issue_id": None,
            "dismiss_reason": None,
            "clarifying_question": None,
        }
    )


async def test_openai_compatible_client_sends_json_schema_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _completion(_plan_json())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    llm = OpenAICompatLLMClient(
        "groq",
        "test-key",
        "llama-test",
        "https://api.groq.test/chat/completions",
        client=client,
    )
    result, provider = await llm.complete_structured("system", "user", AgentPlan)

    assert provider == "groq"
    assert result.intent == "search"
    request_payload = json.loads(requests[0].content)
    assert request_payload["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in request_payload["messages"][0]["content"]
    await client.aclose()


@pytest.mark.parametrize("status_code", [429, 503])
async def test_router_fails_over_from_groq_to_gemini(status_code: int) -> None:
    def groq_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": "temporarily unavailable"})

    gemini_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: _completion(_plan_json()))
    )
    groq_http = httpx.AsyncClient(transport=httpx.MockTransport(groq_handler))
    settings = Settings(
        _env_file=None,
        llm_provider="groq",
        groq_api_key="groq-key",
        gemini_api_key="gemini-key",
    )
    router = FallbackLLMRouter(
        settings,
        {
            "groq": OpenAICompatLLMClient(
                "groq", "groq-key", "groq-model", "https://groq.test", client=groq_http
            ),
            "gemini": OpenAICompatLLMClient(
                "gemini",
                "gemini-key",
                "gemini-model",
                "https://gemini.test",
                client=gemini_client,
            ),
        },
    )

    result, provider = await router.complete_structured("system", "query", AgentPlan)

    assert provider == "gemini"
    assert result.intent == "search"
    await groq_http.aclose()
    await gemini_client.aclose()


async def test_invalid_json_gets_one_corrective_retry() -> None:
    outputs = iter(("not-json", _plan_json()))
    request_count = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return _completion(next(outputs))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    llm = OpenAICompatLLMClient("groq", "test-key", "model", "https://groq.test", client=client)

    result, _ = await llm.complete_structured("system", "query", AgentPlan)

    assert result.intent == "search"
    assert request_count == 2
    await client.aclose()


async def test_router_uses_deterministic_fallback_when_both_providers_fail() -> None:
    provider_calls = {"groq": 0, "gemini": 0}

    def failing_handler(provider: str):
        def handler(_: httpx.Request) -> httpx.Response:
            provider_calls[provider] += 1
            return httpx.Response(503, json={"error": "temporarily unavailable"})

        return handler

    groq_http = httpx.AsyncClient(transport=httpx.MockTransport(failing_handler("groq")))
    gemini_http = httpx.AsyncClient(transport=httpx.MockTransport(failing_handler("gemini")))
    router = FallbackLLMRouter(
        Settings(
            _env_file=None,
            llm_provider="groq",
            groq_api_key="groq-key",
            gemini_api_key="gemini-key",
        ),
        {
            "groq": OpenAICompatLLMClient(
                "groq", "groq-key", "groq-model", "https://groq.test", client=groq_http
            ),
            "gemini": OpenAICompatLLMClient(
                "gemini",
                "gemini-key",
                "gemini-model",
                "https://gemini.test",
                client=gemini_http,
            ),
        },
    )

    result, provider = await router.complete_structured("system", "Find Rust issues", AgentPlan)

    assert provider == "deterministic"
    assert result.intent == "search"
    assert provider_calls == {"groq": 1, "gemini": 1}
    await groq_http.aclose()
    await gemini_http.aclose()


async def test_router_uses_deterministic_fallback_without_api_keys() -> None:
    router = FallbackLLMRouter(Settings(_env_file=None, groq_api_key="", gemini_api_key=""))
    result, provider = await router.complete_structured(
        "system",
        "Find Python GSoC issues from sugarlabs and avoid documentation and CSS",
        AgentPlan,
    )

    assert isinstance(router.deterministic_client, DeterministicRuleBasedLLM)
    assert provider == "deterministic"
    assert result.intent == "search"
    assert result.target_org == "sugarlabs"
    assert result.program_tags == ["gsoc"]
    assert result.preference_delta.add_languages == ["python"]
    assert result.preference_delta.add_excluded_labels == ["css", "documentation"]
