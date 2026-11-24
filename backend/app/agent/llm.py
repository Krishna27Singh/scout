from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.schemas.chat import AgentPlan, AgentSynthesis, IssueRationale, PreferenceDelta
from app.schemas.preferences import ExperienceLevel, UserPreferencesSchema
from app.schemas.search import RetrievedIssue

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "groq_api_key", "groq_model"),
    "gemini": (
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "gemini_api_key",
        "gemini_model",
    ),
}
_LANGUAGES = {
    "c++": ("c++",),
    "c#": ("c#",),
    "javascript": ("javascript", "js"),
    "typescript": ("typescript", "ts"),
    "python": ("python",),
    "rust": ("rust",),
    "java": ("java",),
    "go": ("golang",),
    "ruby": ("ruby",),
    "php": ("php",),
}
_EXCLUDED_LABEL_ALIASES = {
    "documentation": ("documentation", "docs", "doc"),
    "css": ("css", "styling"),
    "frontend": ("frontend", "front-end"),
}
_ORG_WORDS = {"python", "rust", "java", "golang", "javascript", "typescript", "gsoc"}


class StructuredLLMClient(Protocol):
    async def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> tuple[T, str]:
        """Return validated structured output and the provider name."""


class StructuredOutputError(RuntimeError):
    """Raised when a provider fails to produce schema-valid JSON after retry."""


class OpenAICompatLLMClient:
    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError(f"API key is required for provider {provider}")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None

    async def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> tuple[T, str]:
        schema = json.dumps(response_model.model_json_schema(), ensure_ascii=True)
        schema_instruction = (
            "Return only a JSON object that validates against this JSON Schema. "
            f"Do not include markdown fences or additional keys. Schema: {schema}"
        )
        correction: str | None = None
        previous_output = ""
        for attempt in range(2):
            messages = [
                {"role": "system", "content": f"{system_prompt}\n\n{schema_instruction}"},
                {"role": "user", "content": user_prompt},
            ]
            if correction is not None:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous response did not validate. Correct it and return "
                            f"only valid JSON. Validation error: {correction}\n"
                            f"Previous response: {previous_output}"
                        ),
                    }
                )
            response = await self._client.post(
                self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                },
            )
            response.raise_for_status()
            payload = response.json()
            output = ""
            try:
                output = payload["choices"][0]["message"]["content"]
                if not isinstance(output, str):
                    raise ValueError("Provider response content was not a string")
                validated = response_model.model_validate_json(output)
                return validated, self.provider
            except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
                correction = str(exc)
                previous_output = output if isinstance(output, str) else repr(payload)
                if attempt == 1:
                    break
        raise StructuredOutputError(
            f"{self.provider} returned invalid structured output after one corrective retry"
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class DeterministicRuleBasedLLM:
    async def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> tuple[T, str]:
        if response_model is AgentPlan:
            result = response_model.model_validate(build_agent_plan(user_prompt))
        elif response_model is AgentSynthesis:
            result = response_model.model_validate(
                _build_deterministic_synthesis(user_prompt).model_dump()
            )
        else:
            raise TypeError(
                "DeterministicRuleBasedLLM supports AgentPlan and AgentSynthesis output"
            )
        return result, "deterministic"

    @staticmethod
    def build_grounded_rationale(
        issue: RetrievedIssue,
        preferences: UserPreferencesSchema,
    ) -> str:
        details: list[str] = []
        if issue.primary_language:
            if issue.primary_language.casefold() in preferences.preferred_languages:
                details.append(f"uses your preferred {issue.primary_language} language")
            else:
                details.append(f"is written in {issue.primary_language}")
        if "gsoc" in {tag.casefold() for tag in issue.program_tags}:
            details.append("is tagged for GSoC")
        if issue.labels:
            details.append(f"has labels: {', '.join(issue.labels[:3])}")
        if issue.scores.maintainer_score >= 0.6:
            details.append("comes from a repository with strong maintainer activity")
        if issue.scores.experience_boost > 0.5:
            details.append(f"its labels fit your {preferences.experience_level} experience level")
        if not details:
            details.append("matched your search terms and retrieval filters")
        return "This issue " + "; ".join(details) + "."


class FallbackLLMRouter:
    def __init__(
        self,
        settings: Settings | None = None,
        provider_clients: Mapping[str, StructuredLLMClient] | None = None,
        deterministic_client: StructuredLLMClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.deterministic_client = deterministic_client or DeterministicRuleBasedLLM()
        self.provider_clients: dict[str, StructuredLLMClient] = (
            dict(provider_clients) if provider_clients is not None else self._configured_clients()
        )

    def _configured_clients(self) -> dict[str, StructuredLLMClient]:
        clients: dict[str, StructuredLLMClient] = {}
        for provider, (url, key_name, model_name) in _PROVIDERS.items():
            api_key = getattr(self.settings, key_name)
            if api_key:
                clients[provider] = OpenAICompatLLMClient(
                    provider=provider,
                    api_key=api_key,
                    model=getattr(self.settings, model_name),
                    base_url=url,
                    timeout_seconds=self.settings.llm_timeout_seconds,
                )
        return clients

    async def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> tuple[T, str]:
        available = list(self.provider_clients)
        primary = self.settings.llm_provider
        ordered = ([primary] if primary in available else []) + [
            provider for provider in available if provider != primary
        ]
        for provider in ordered:
            try:
                return await self.provider_clients[provider].complete_structured(
                    system_prompt, user_prompt, response_model
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                logger.warning(
                    "LLM provider request failed; trying fallback",
                    extra={"provider": provider, "error": str(exc)},
                )
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "LLM provider returned an HTTP error",
                    extra={
                        "provider": provider,
                        "status_code": exc.response.status_code,
                    },
                )
                if exc.response.status_code not in RETRYABLE_STATUS_CODES:
                    break
            except StructuredOutputError as exc:
                logger.warning(
                    "LLM provider returned invalid structured output",
                    extra={"provider": provider, "error": str(exc)},
                )
                break

        result, provider = await self.deterministic_client.complete_structured(
            system_prompt, user_prompt, response_model
        )
        return result, provider

    async def aclose(self) -> None:
        for client in self.provider_clients.values():
            close = getattr(client, "aclose", None)
            if close is not None:
                await close()


def build_agent_plan(message: str) -> dict[str, object]:
    normalized = message.casefold()
    repo_match = re.search(r"\b([a-z0-9_.-]+)/([a-z0-9_.-]+)\b", message, re.IGNORECASE)
    target_repo = (
        f"{repo_match.group(1).rstrip('.,')}/{repo_match.group(2).rstrip('.,')}"
        if repo_match
        else None
    )
    target_org = _find_target_org(message, target_repo)
    detected_languages = {
        language
        for language, aliases in _LANGUAGES.items()
        if any(
            re.search(rf"(?<![\w+#]){re.escape(alias)}(?![\w+#])", normalized) for alias in aliases
        )
    }
    remove_languages = {
        language
        for language, aliases in _LANGUAGES.items()
        if any(
            re.search(
                rf"\b(?:remove|forget|avoid|exclude|never|no longer prefer|"
                rf"don['’]t want|do not want)\s+(?:the\s+)?{re.escape(alias)}(?![\w+#])",
                normalized,
            )
            for alias in aliases
        )
    }
    languages = sorted(detected_languages - remove_languages)
    excluded_labels = _find_excluded_labels(normalized)
    excluded_topics = _find_excluded_topics(normalized)
    experience: ExperienceLevel | None = next(
        (level for level in ("beginner", "intermediate", "advanced") if level in normalized),
        None,
    )
    delta = PreferenceDelta(
        add_languages=languages,
        remove_languages=sorted(remove_languages),
        add_orgs=[target_org] if target_org else [],
        add_excluded_labels=excluded_labels,
        add_excluded_topics=excluded_topics,
        experience_level=experience,
        raw_notes=message
        if languages or remove_languages or target_org or excluded_labels or excluded_topics
        else None,
    )

    dismiss_match = re.search(
        r"\b(?:dismiss|hide|remove)\s+(?:the\s+)?(?:issue\s*)?#?(\d+)\b",
        normalized,
    )
    if dismiss_match:
        reason_match = re.search(r"\bbecause\s+(.+)$", message, re.IGNORECASE)
        return {
            "intent": "dismiss",
            "search_query": "",
            "preference_delta": delta,
            "target_org": target_org,
            "target_repo": target_repo,
            "program_tags": ["gsoc"] if "gsoc" in normalized else [],
            "dismiss_issue_id": int(dismiss_match.group(1)),
            "dismiss_reason": reason_match.group(1).strip() if reason_match else None,
        }

    has_search_request = re.search(
        r"\b(?:issue|issues|search|find|show|recommend|match|bugs|tasks)\b", normalized
    )
    has_preference_cue = re.search(
        r"\b(?:prefer|preference|remember|i like|i want|avoid|exclude|never|no)\b",
        normalized,
    )
    has_preference_delta = bool(
        languages
        or remove_languages
        or target_org
        or excluded_labels
        or excluded_topics
        or experience
    )
    if not has_search_request and has_preference_delta and has_preference_cue:
        return {
            "intent": "update_preferences",
            "search_query": "",
            "preference_delta": delta,
            "target_org": target_org,
            "target_repo": target_repo,
            "program_tags": [],
        }

    if len(normalized.split()) <= 2 and normalized.strip() in {"hi", "hello", "help", "hey"}:
        return {
            "intent": "clarify",
            "search_query": "",
            "preference_delta": delta,
            "clarifying_question": "What kinds of open-source issues would you like to find?",
        }

    plan: dict[str, object] = {
        "intent": "search",
        "search_query": message.strip(),
        "preference_delta": delta,
        "target_org": target_org,
        "target_repo": target_repo,
        "program_tags": ["gsoc"] if "gsoc" in normalized else [],
    }
    return plan


def _build_deterministic_synthesis(user_prompt: str) -> AgentSynthesis:
    payload = json.loads(user_prompt)
    preferences = UserPreferencesSchema.model_validate(payload["preferences"])
    issues = [RetrievedIssue.model_validate_json(json.dumps(item)) for item in payload["matches"]]
    intent = str(payload["intent"])
    if intent == "search":
        assistant_message = (
            f"I found {len(issues)} issue match{'es' if len(issues) != 1 else ''}."
            if issues
            else "I couldn't find matching open issues with those filters. "
            "Try broadening your search."
        )
    elif intent == "update_preferences":
        assistant_message = "I saved your preference updates for future issue searches."
    elif intent == "dismiss":
        assistant_message = str(payload.get("fallback_message", "I updated your dismissals."))
    else:
        assistant_message = str(
            payload.get(
                "clarifying_question",
                "Could you clarify what you would like Scout to do?",
            )
        )
    return AgentSynthesis(
        assistant_message=assistant_message,
        rationales=[
            IssueRationale(
                issue_id=issue.id,
                match_reason=DeterministicRuleBasedLLM.build_grounded_rationale(issue, preferences),
            )
            for issue in issues
        ],
    )


def _find_target_org(message: str, target_repo: str | None) -> str | None:
    if target_repo is not None:
        return target_repo.split("/", maxsplit=1)[0].casefold()
    match = re.search(
        r"\b(?:org(?:anization)?(?:\s+(?:called|named))?|from)\s+([a-z0-9_.-]+)",
        message,
        re.IGNORECASE,
    )
    if match is None:
        match = re.search(r"\b([a-z0-9_.-]+)\s+org(?:anization)?\b", message, re.IGNORECASE)
    if match is None:
        match = re.search(r"\b(?:in|at)\s+([a-z0-9_.-]+)\b", message, re.IGNORECASE)
    if match is None:
        return None
    org = match.group(1).casefold()
    return None if org in _ORG_WORDS else org


def _find_excluded_labels(message: str) -> list[str]:
    negative_segments = re.findall(
        r"\b(?:no|never|avoid|exclude|excluding|without)\b([^.!?;]*)",
        message,
        re.IGNORECASE,
    )
    found: set[str] = set()
    for segment in negative_segments:
        for normalized, aliases in _EXCLUDED_LABEL_ALIASES.items():
            if any(
                re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", segment, re.IGNORECASE)
                for alias in aliases
            ):
                found.add(normalized)
    return sorted(found)


def _find_excluded_topics(message: str) -> list[str]:
    matches = re.findall(
        r"\b(?:avoid|exclude|excluding|never|no)\s+(?:repository\s+)?topics?\s+([a-z0-9_.-]+)",
        message,
        re.IGNORECASE,
    )
    return sorted({item.casefold() for item in matches})
