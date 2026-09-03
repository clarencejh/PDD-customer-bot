"""Provider-neutral async LiteLLM transport.

Only the small, portable Chat Completions contract is built here.  Provider
identity and endpoint policy come from :mod:`utils.llm_provider`; LiteLLM is
called directly and no proxy process or environment-variable setup is needed.
"""

from __future__ import annotations

import ipaddress
import inspect
import re
import socket
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import urlsplit

from utils.llm_provider import (
    EndpointTrustMode,
    LLMProfile,
    LLMProvider,
    ProfileValidationError,
    ToolPolicy,
    build_llm_profile,
    provider_spec,
    validate_endpoint,
)
from utils.logger_loguru import get_logger

logger = get_logger("LLMTransport")

# Lazy import keeps application startup from importing LiteLLM's large provider
# catalogue before an account actually initializes its LLM client.  Tests and
# callers may replace this value with a small fake SDK.
litellm: Any = None


class AuthenticationError(Exception):
    """Test-friendly marker with the same category as LiteLLM auth errors."""


class RateLimitError(Exception):
    """Test-friendly marker with the same category as LiteLLM rate limits."""


class LLMErrorCategory(str, Enum):
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    PARAMETER = "parameter"
    TOOL_CAPABILITY = "tool_capability"
    PROVIDER = "provider"
    GENERIC = "generic"


class EndpointPolicyError(ValueError):
    """Raised before an API key is handed to an unsafe endpoint."""


class LLMTransportError(RuntimeError):
    """Safe runtime error with a stable recovery category."""

    def __init__(
        self,
        category: LLMErrorCategory,
        safe_message: str,
        *,
        provider: str,
        model_name: str,
        detail: str = "",
    ) -> None:
        super().__init__(safe_message)
        self.category = category
        self.safe_message = safe_message
        self.provider = provider
        self.model_name = model_name
        # Redacted provider/runtime text for operator-facing surfaces only.
        # ``str()`` and ``safe_message`` stay free of it so customer-facing
        # paths cannot echo a provider payload.
        self.detail = detail


@dataclass(frozen=True)
class NormalizedFunction:
    name: str
    arguments: str


@dataclass(frozen=True)
class NormalizedToolCall:
    id: str
    function: NormalizedFunction
    type: str = "function"


@dataclass(frozen=True)
class NormalizedResponse:
    content: Optional[str]
    tool_calls: List[NormalizedToolCall]
    usage: Dict[str, Any]
    raw_response: Any


def _load_litellm() -> Any:
    global litellm
    if litellm is None:
        import litellm as sdk

        litellm = sdk
    return litellm


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _usage_dict(usage: Any) -> Dict[str, Any]:
    if usage is None:
        return {}
    if isinstance(usage, Mapping):
        return dict(usage)
    model_dump = getattr(usage, "model_dump", None)
    if callable(model_dump):
        try:
            return dict(model_dump(exclude_none=True))
        except Exception:
            return {}
    result: Dict[str, Any] = {}
    for key in ("total_tokens", "prompt_tokens", "completion_tokens"):
        value = getattr(usage, key, None)
        if value is not None:
            result[key] = value
    return result


def normalize_response(response: Any) -> NormalizedResponse:
    choices = _field(response, "choices", []) or []
    first_choice = choices[0] if choices else {}
    message = _field(first_choice, "message", {}) or {}
    raw_tool_calls = _field(message, "tool_calls", []) or []
    tool_calls: List[NormalizedToolCall] = []
    for index, raw_call in enumerate(raw_tool_calls):
        function = _field(raw_call, "function", {}) or {}
        arguments = _field(function, "arguments", "")
        if not isinstance(arguments, str):
            arguments = str(arguments)
        tool_calls.append(
            NormalizedToolCall(
                id=str(_field(raw_call, "id", f"tool-call-{index}")),
                type=str(_field(raw_call, "type", "function")),
                function=NormalizedFunction(
                    name=str(_field(function, "name", "")),
                    arguments=arguments,
                ),
            )
        )
    return NormalizedResponse(
        content=_field(message, "content"),
        tool_calls=tool_calls,
        usage=_usage_dict(_field(response, "usage")),
        raw_response=response,
    )


def _unsafe_ip(address: str) -> bool:
    try:
        value = ipaddress.ip_address(address)
    except ValueError:
        return False
    return bool(
        value.is_private
        or value.is_loopback
        or value.is_link_local
        or value.is_reserved
        or value.is_unspecified
        or value.is_multicast
        or ipaddress.ip_network("100.64.0.0/10").overlaps(
            ipaddress.ip_network(f"{value}/{value.max_prefixlen}")
        )
    )


def _is_metadata_host(host: str) -> bool:
    normalized = host.strip("[]").lower()
    return normalized in {
        "169.254.169.254",
        "100.100.100.200",
        "metadata.google.internal",
        "instance-data",
    } or normalized.endswith(".metadata.google.internal")


def _is_fake_ip(address: str) -> bool:
    """True for an IPv4 or macOS synthesized IPv6 fake-ip address.

    Some macOS resolver paths return an RFC 2544 fake IPv4 result twice: once
    as ``198.18.x.x`` and once as the synthesized IPv6 form
    ``::ffff:0:<embedded-v4>``.  The latter is still routed by the hostname
    through the proxy and must not be treated as a real private destination.
    """
    try:
        value = ipaddress.ip_address(address)
    except ValueError:
        return False

    fake_network = ipaddress.ip_network("198.18.0.0/15")
    if isinstance(value, ipaddress.IPv4Address):
        return value in fake_network

    mapped = value.ipv4_mapped
    if mapped is not None:
        return mapped in fake_network

    # macOS may encode the fake IPv4 address as ::ffff:0:<hex IPv4> rather
    # than the canonical IPv4-mapped IPv6 representation.
    packed = value.packed
    if (
        packed[:8] == b"\x00" * 8
        and packed[8:10] == b"\xff\xff"
        and packed[10:12] == b"\x00\x00"
    ):
        embedded = ipaddress.IPv4Address(packed[-4:])
        return embedded in fake_network
    return False


def validate_transport_endpoint(profile: LLMProfile) -> str:
    """Perform URL, DNS target, and endpoint trust checks before a call."""
    try:
        validate_endpoint(
            profile.provider,
            profile.api_base,
            profile.endpoint_trust_mode,
        )
    except ProfileValidationError as exc:
        raise EndpointPolicyError(exc.safe_message) from None

    if not profile.api_base:
        return ""

    parsed = urlsplit(profile.api_base)
    host = (parsed.hostname or "").lower()
    if _is_metadata_host(host):
        raise EndpointPolicyError("Base URL 不能指向云实例元数据或链路本地地址")
    if profile.endpoint_trust_mode is EndpointTrustMode.LOCAL:
        return profile.api_base

    try:
        addresses = socket.getaddrinfo(
            host,
            parsed.port or 443,
            type=socket.SOCK_STREAM,
        )
    except OSError:
        raise EndpointPolicyError("Base URL 无法解析，已阻止本次请求") from None

    # Proxy-mediated DNS (fake-ip TUN such as Clash/mihomo) answers every query
    # inside that range and routes by hostname, so per-address checks are both
    # impossible and unnecessary; the range is otherwise unroutable.
    if addresses and all(
        _is_fake_ip(item[4][0] if item[4] else "") for item in addresses
    ):
        return profile.api_base

    for item in addresses:
        sockaddr = item[4]
        address = sockaddr[0] if sockaddr else ""
        if _unsafe_ip(address) or _is_metadata_host(address):
            raise EndpointPolicyError("Base URL 解析到了本地、私有或元数据地址")
    return profile.api_base


def validate_redirect_origin(origin: str, redirected: str) -> None:
    """Reject a redirect that changes the trusted scheme/host/port."""
    source = urlsplit(origin)
    target = urlsplit(redirected)
    source_port = source.port or (443 if source.scheme == "https" else 80)
    target_port = target.port or (443 if target.scheme == "https" else 80)
    if (
        source.scheme.lower() != "https"
        or target.scheme.lower() != "https"
        or source.hostname != target.hostname
        or source_port != target_port
    ):
        raise EndpointPolicyError("Base URL 的跨主机或降级重定向已被阻止")


def build_chat_payload(
    profile: LLMProfile,
    messages: List[Dict[str, Any]],
    *,
    temperature: float = 0.3,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: str = "auto",
    use_tools: bool = True,
    response_format: Optional[Dict[str, Any]] = None,
    max_tokens: Optional[int] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Build the minimal portable LiteLLM request payload."""
    validated_profile = build_llm_profile(
        profile,
        require_api_key=True,
        require_confirmation=use_tools,
    )
    validate_transport_endpoint(validated_profile)

    payload: Dict[str, Any] = {
        "model": validated_profile.route_model,
        "messages": messages,
        "temperature": temperature,
        "api_key": validated_profile.api_key,
    }
    # LiteLLM/provider defaults resolve the built-in endpoint.  Only an
    # explicit user override is forwarded as base_url.
    if validated_profile.api_base:
        payload["base_url"] = validated_profile.api_base
    if timeout is not None:
        payload["timeout"] = timeout
    if response_format is not None:
        payload["response_format"] = response_format
    # 便携字段 max_tokens 仅在上层显式传入时下发（连接探针等场景），默认请求保持最小载荷。
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if use_tools and validated_profile.tool_policy is ToolPolicy.ENABLED and tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice
    return payload


def classify_exception(exc: BaseException) -> LLMErrorCategory:
    """Map provider/SDK failures with stable precedence and no raw output."""
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if any(marker in name for marker in ("authentication", "authenticationerror", "apikey", "unauthorized")):
        return LLMErrorCategory.AUTHENTICATION
    if "ratelimit" in name or "rate_limit" in name or "too many requests" in text:
        return LLMErrorCategory.RATE_LIMIT
    if (
        "tool" in name
        or "function" in name
        or "unsupported tool" in text
        or "tool_choice" in text
        or "function calling" in text
    ):
        return LLMErrorCategory.TOOL_CAPABILITY
    if any(marker in name for marker in ("badrequest", "invalidrequest", "unsupportedparams", "param")):
        return LLMErrorCategory.PARAMETER
    if any(marker in name for marker in ("connection", "timeout", "apierror", "serviceunavailable", "servererror")):
        return LLMErrorCategory.PROVIDER
    return LLMErrorCategory.GENERIC


def safe_error_message(category: LLMErrorCategory) -> str:
    return {
        LLMErrorCategory.AUTHENTICATION: "模型鉴权失败，请检查供应商和 API Key",
        LLMErrorCategory.RATE_LIMIT: "模型请求受到限流，请稍后重试或调整供应商",
        LLMErrorCategory.PARAMETER: "模型请求参数不被当前供应商接受，请检查模型和配置",
        LLMErrorCategory.TOOL_CAPABILITY: "当前模型或供应商不支持所需的工具调用，请更换模型",
        LLMErrorCategory.PROVIDER: "模型供应商暂时不可用，请检查 Base URL 或稍后重试",
        LLMErrorCategory.GENERIC: "模型请求失败，请检查配置并稍后重试",
    }[category]


# Token shapes providers echo back inside their own error payloads.  Stripping
# the configured key is the real defence; this is a narrow backstop for a key
# that arrives reshaped, kept long enough not to swallow plain error codes.
_SECRET_PATTERN = re.compile(r"(?i)\b(?:sk|xai|gsk)[-_][A-Za-z0-9\-_]{16,}")
_BEARER_PATTERN = re.compile(r"(?i)(authorization|bearer)\s*[:=]?\s*\S+")
_DETAIL_LIMIT = 400


def error_detail(exc: BaseException, *secrets: Optional[str]) -> str:
    """Redacted one-line description of a failure, for operator surfaces.

    The provider's own text is the only thing that distinguishes "model does
    not exist" from "insufficient balance", so it is worth showing — but it can
    echo the credential that was sent, so every known secret is stripped first.
    """
    text = " ".join(str(exc).split())
    for secret in secrets:
        if secret and len(secret) >= 6:
            text = text.replace(secret, "***")
    text = _BEARER_PATTERN.sub(r"\1 ***", text)
    text = _SECRET_PATTERN.sub("***", text)
    if len(text) > _DETAIL_LIMIT:
        text = f"{text[:_DETAIL_LIMIT]}…"
    name = type(exc).__name__
    return f"{name}: {text}" if text else name


def _build_redirect_safe_client(profile: LLMProfile, timeout: Optional[float]) -> Any:
    """Create a per-request LiteLLM client that never follows redirects.

    LiteLLM's OpenAI-compatible handlers accept either their own
    ``AsyncHTTPHandler`` (DeepSeek's route) or an ``AsyncOpenAI`` client (the
    other built-in OpenAI-compatible routes).  Keeping the client per call
    avoids a mutable process-global HTTP policy and prevents a provider from
    changing another account's transport settings.
    """
    if profile.provider is LLMProvider.DEEPSEEK:
        from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

        handler = AsyncHTTPHandler(timeout=timeout)
        # LiteLLM 1.96.2 constructs this client with redirects enabled.  The
        # handler exposes the underlying httpx client, so turn the policy off
        # before handing it to LiteLLM's DeepSeek adapter.
        handler.client.follow_redirects = False
        return handler

    import httpx
    from openai import AsyncOpenAI

    http_client = httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
    )
    return AsyncOpenAI(
        api_key=profile.api_key,
        base_url=profile.effective_api_base or provider_spec(profile.provider).default_api_base,
        http_client=http_client,
        timeout=timeout,
    )


async def _close_transport_client(client: Any) -> None:
    close = getattr(client, "close", None)
    if not callable(close):
        return
    result = close()
    if inspect.isawaitable(result):
        await result


async def async_completion(
    profile: LLMProfile,
    messages: List[Dict[str, Any]],
    *,
    temperature: float = 0.3,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: str = "auto",
    use_tools: bool = True,
    response_format: Optional[Dict[str, Any]] = None,
    max_tokens: Optional[int] = None,
    timeout: Optional[float] = None,
) -> NormalizedResponse:
    payload = build_chat_payload(
        profile,
        messages,
        temperature=temperature,
        tools=tools,
        tool_choice=tool_choice,
        use_tools=use_tools,
        response_format=response_format,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    try:
        sdk = _load_litellm()
        transport_client = _build_redirect_safe_client(
            build_llm_profile(profile, require_confirmation=False),
            timeout,
        )
    except (EndpointPolicyError, ProfileValidationError):
        raise
    except Exception as exc:
        # Importing LiteLLM or building its HTTP client is local runtime work,
        # not a provider response.  It used to escape the handler below and
        # reach the UI as a bare class name (a frozen build missing LiteLLM's
        # bundled JSON surfaced only as "FileNotFoundError").
        logger.error(
            "LLM transport setup failed; "
            f"error_type={type(exc).__name__} provider={profile.provider.value}"
        )
        raise LLMTransportError(
            LLMErrorCategory.GENERIC,
            "本地 LLM 传输层初始化失败，请检查运行环境依赖是否完整",
            provider=profile.provider.value,
            model_name=profile.model_name,
            detail=error_detail(exc, profile.api_key),
        ) from None
    payload["client"] = transport_client
    try:
        response = sdk.acompletion(**payload)
        if inspect.isawaitable(response):
            response = await response
        return normalize_response(response)
    except Exception as exc:
        category = classify_exception(exc)
        logger.error(
            "LLM request failed; "
            f"category={category.value} error_type={type(exc).__name__} "
            f"provider={profile.provider.value} model={profile.model_name[:80]}"
        )
        raise LLMTransportError(
            category,
            safe_error_message(category),
            provider=profile.provider.value,
            model_name=profile.model_name,
            detail=error_detail(exc, profile.api_key),
        ) from None
    finally:
        await _close_transport_client(transport_client)


__all__ = [
    "AuthenticationError",
    "EndpointPolicyError",
    "LLMErrorCategory",
    "LLMTransportError",
    "NormalizedFunction",
    "NormalizedResponse",
    "NormalizedToolCall",
    "RateLimitError",
    "async_completion",
    "build_chat_payload",
    "classify_exception",
    "error_detail",
    "litellm",
    "normalize_response",
    "safe_error_message",
    "validate_redirect_origin",
    "validate_transport_endpoint",
]
