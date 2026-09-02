"""CustomerAgent-facing wrapper around the shared LiteLLM transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from utils.llm_provider import (
    LLMProfile,
    LLMProvider,
    build_llm_profile,
    provider_spec,
)
from utils.llm_transport import NormalizedResponse, async_completion
from utils.logger_loguru import get_logger

logger = get_logger("LLMClient")


@dataclass
class LLMResponse:
    """Stable response contract consumed by the existing agent loop."""

    content: Optional[str]
    tool_calls: List[Any]
    raw_response: Any
    usage: Dict[str, Any] | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMClient:
    """Per-account LLM client with an immutable profile snapshot."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model_name: Optional[str] = None,
        temperature: float = 0.3,
        tools: Optional[List[Dict[str, Any]]] = None,
        *,
        provider: LLMProvider | str | None = None,
        profile: Optional[LLMProfile] = None,
    ):
        if profile is None:
            if provider is None:
                raise ValueError("LLMClient requires an explicit provider or validated profile")
            profile = build_llm_profile(
                {
                    "provider": provider,
                    "model_name": model_name or "",
                    "api_key": api_key or "",
                    "api_base": api_base or "",
                },
                require_confirmation=False,
            )
        else:
            # The profile has already passed the configuration boundary.  The
            # transport repeats capability/trust checks at call time.
            profile = build_llm_profile(
                profile,
                require_api_key=True,
                require_confirmation=False,
            )

        self.profile = profile
        self.api_key = profile.api_key
        self.api_base = profile.api_base
        self.model_name = profile.model_name
        self.provider = profile.provider
        self.temperature = temperature
        self.tools = tools or []
        self._initialized = False

    async def initialize(self) -> None:
        """Validate the snapshot; LiteLLM owns the request client lifecycle."""
        self.profile = build_llm_profile(
            self.profile,
            require_api_key=True,
            require_confirmation=False,
        )
        self._initialized = True
        logger.debug(
            "LLM client initialized; "
            f"provider={self.profile.provider.value} model={self.profile.model_name}"
        )

    async def close(self) -> None:
        """Release the account-owned logical client snapshot."""
        self._initialized = False

    async def test_connection(self) -> None:
        """Minimal completion probe used by the settings UI and auto-reply checks."""
        if not self._initialized:
            raise RuntimeError("LLM 客户端未初始化，请先调用 initialize()")
        await async_completion(
            self.profile,
            [{"role": "user", "content": "Reply with OK."}],
            temperature=0,
            use_tools=False,
            max_tokens=1,
            timeout=60.0,
        )

    async def list_models(self) -> List[str]:
        """Return model IDs exposed by an OpenAI-compatible base URL."""
        if not self._initialized:
            raise RuntimeError("LLM 客户端未初始化，请先调用 initialize()")
        import httpx
        from openai import AsyncOpenAI

        profile = build_llm_profile(
            self.profile,
            require_api_key=True,
            require_confirmation=False,
        )
        http_client = httpx.AsyncClient(timeout=60.0, follow_redirects=False)
        client = AsyncOpenAI(
            api_key=profile.api_key,
            base_url=profile.effective_api_base
            or provider_spec(profile.provider).default_api_base,
            http_client=http_client,
            timeout=60.0,
        )
        try:
            page = await client.models.list()
            model_ids = {
                str(model.id).strip()
                for model in page.data
                if getattr(model, "id", None)
            }
            return sorted(model_ids, key=str.casefold)
        finally:
            close = getattr(client, "close", None) or getattr(
                client, "aclose", None
            )
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tool_choice: str = "auto",
        *,
        use_tools: bool = True,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> LLMResponse:
        if not self._initialized:
            raise RuntimeError("LLM 客户端未初始化，请先调用 initialize()")

        normalized: NormalizedResponse = await async_completion(
            self.profile,
            messages,
            temperature=self.temperature,
            tools=self.tools,
            tool_choice=tool_choice,
            use_tools=use_tools and bool(self.tools),
            response_format=response_format,
            timeout=60.0,
        )
        if normalized.tool_calls:
            logger.info(
                "LLM selected tools; "
                f"provider={self.profile.provider.value} "
                f"count={len(normalized.tool_calls)}"
            )
        else:
            logger.debug(
                "LLM returned text; "
                f"provider={self.profile.provider.value} "
                f"length={len(str(normalized.content or ''))}"
            )
        return LLMResponse(
            content=normalized.content,
            tool_calls=normalized.tool_calls,
            raw_response=normalized.raw_response,
            usage=normalized.usage,
        )


__all__ = ["LLMClient", "LLMResponse"]
