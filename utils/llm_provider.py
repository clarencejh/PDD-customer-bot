"""Shared provider registry, profile validation, and capability policy.

The application stores a provider identity explicitly.  A URL is only an
endpoint override; it is never used as a runtime provider guess.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import copy
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Mapping
from urllib.parse import urlsplit


class LLMProvider(str, Enum):
    DEEPSEEK = "deepseek"
    VOLCENGINE = "volcengine"
    OPENAI_COMPATIBLE = "openai_compatible"
    KIMI = "kimi"
    ZHIPU = "zhipu"
    QWEN = "qwen"


class CapabilityState(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class EndpointTrustMode(str, Enum):
    DEFAULT = "default"
    EXPLICIT = "explicit"
    LOCAL = "local"


class ToolPolicy(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


@dataclass(frozen=True)
class ProviderSpec:
    provider: LLMProvider
    label: str
    litellm_prefix: str
    default_api_base: str
    requires_api_base: bool = False


@dataclass(frozen=True)
class CapabilityDecision:
    state: CapabilityState
    provider: LLMProvider
    model_name: str
    reason: str

    @property
    def requires_confirmation(self) -> bool:
        return self.state is CapabilityState.UNKNOWN


@dataclass(frozen=True)
class LLMProfile:
    provider: LLMProvider
    model_name: str
    api_key: str
    api_base: str = ""
    endpoint_trust_mode: EndpointTrustMode = EndpointTrustMode.DEFAULT
    tool_policy: ToolPolicy = ToolPolicy.ENABLED
    capability_confirmation: str = ""
    tool_trust_confirmation: str = ""

    @property
    def route_model(self) -> str:
        return provider_spec(self.provider).litellm_prefix + self.model_name

    @property
    def effective_api_base(self) -> str:
        return self.api_base or provider_spec(self.provider).default_api_base

    @property
    def normalized_api_base(self) -> str:
        return normalize_base_url(self.api_base)


class ProfileValidationError(ValueError):
    """Safe, actionable profile validation error.

    ``safe_message`` deliberately excludes API keys and raw provider errors so
    it can be shown by the settings UI and logged by runtime callers.
    """

    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        field: str | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.field = field


PROVIDER_SPECS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        LLMProvider.DEEPSEEK,
        "DeepSeek",
        "deepseek/",
        "https://api.deepseek.com",
    ),
    ProviderSpec(
        LLMProvider.VOLCENGINE,
        "火山引擎",
        "volcengine/",
        "https://ark.cn-beijing.volces.com/api/v3",
    ),
    ProviderSpec(
        LLMProvider.OPENAI_COMPATIBLE,
        "OpenAI-compatible",
        "openai/",
        "",
        requires_api_base=True,
    ),
    ProviderSpec(
        LLMProvider.KIMI,
        "Kimi/Moonshot",
        "moonshot/",
        "https://api.moonshot.cn/v1",
    ),
    ProviderSpec(
        LLMProvider.ZHIPU,
        "智谱/Z.AI",
        "zai/",
        "https://open.bigmodel.cn/api/paas/v4",
    ),
    ProviderSpec(
        LLMProvider.QWEN,
        "Qwen/DashScope",
        "dashscope/",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
)

_SPEC_BY_PROVIDER = {spec.provider: spec for spec in PROVIDER_SPECS}
_PROVIDER_ALIASES = {
    "openai": LLMProvider.OPENAI_COMPATIBLE,
    "openai-compatible": LLMProvider.OPENAI_COMPATIBLE,
    "openai_compatible": LLMProvider.OPENAI_COMPATIBLE,
    "openai compatible": LLMProvider.OPENAI_COMPATIBLE,
    "volc": LLMProvider.VOLCENGINE,
    "volcengine": LLMProvider.VOLCENGINE,
    "moonshot": LLMProvider.KIMI,
    "kimi/moonshot": LLMProvider.KIMI,
    "zai": LLMProvider.ZHIPU,
    "glm": LLMProvider.ZHIPU,
    "dashscope": LLMProvider.QWEN,
}


def provider_spec(provider: LLMProvider | str) -> ProviderSpec:
    """Return the single registry entry for a provider identity."""
    normalized = normalize_provider(provider)
    try:
        return _SPEC_BY_PROVIDER[normalized]
    except KeyError as exc:
        raise ProfileValidationError(
            "invalid_provider",
            f"不支持的模型供应商: {provider}",
            field="provider",
        ) from exc


def normalize_provider(provider: LLMProvider | str | None) -> LLMProvider:
    if isinstance(provider, LLMProvider):
        return provider
    value = str(provider or "").strip().lower()
    if value in _PROVIDER_ALIASES:
        return _PROVIDER_ALIASES[value]
    try:
        return LLMProvider(value)
    except ValueError as exc:
        raise ProfileValidationError(
            "invalid_provider",
            f"不支持的模型供应商: {provider or '未选择'}",
            field="provider",
        ) from exc


def provider_choices() -> tuple[tuple[str, str], ...]:
    return tuple((spec.provider.value, spec.label) for spec in PROVIDER_SPECS)


def normalize_base_url(value: str | None) -> str:
    return str(value or "").strip().rstrip("/")


def infer_provider(api_base: str | None) -> LLMProvider:
    """Infer a provider only for one-time legacy migration."""
    base = normalize_base_url(api_base)
    if not base:
        return LLMProvider.OPENAI_COMPATIBLE
    host = (urlsplit(base).hostname or "").lower()
    if host == "api.deepseek.com":
        return LLMProvider.DEEPSEEK
    if host == "ark.cn-beijing.volces.com" or host.endswith(".volces.com"):
        return LLMProvider.VOLCENGINE
    if host == "api.moonshot.cn" or host.endswith(".moonshot.cn"):
        return LLMProvider.KIMI
    if host == "open.bigmodel.cn" or host.endswith(".bigmodel.cn"):
        return LLMProvider.ZHIPU
    if host == "dashscope.aliyuncs.com" or host.endswith(".dashscope.aliyuncs.com"):
        return LLMProvider.QWEN
    return LLMProvider.OPENAI_COMPATIBLE


def migrate_llm_config(config_data: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    """Add the explicit provider/profile fields to a legacy config copy."""
    migrated = copy.deepcopy(dict(config_data))
    llm_value = migrated.get("llm")
    llm = copy.deepcopy(llm_value) if isinstance(llm_value, Mapping) else {}
    changed = not isinstance(llm_value, Mapping)

    raw_provider = llm.get("provider")
    try:
        provider = normalize_provider(raw_provider) if raw_provider else infer_provider(llm.get("api_base"))
    except ProfileValidationError:
        provider = infer_provider(llm.get("api_base"))
    if llm.get("provider") != provider.value:
        llm["provider"] = provider.value
        changed = True

    defaults = {
        "endpoint_trust_mode": (
            EndpointTrustMode.EXPLICIT.value
            if normalize_base_url(llm.get("api_base"))
            else EndpointTrustMode.DEFAULT.value
        ),
        "tool_policy": ToolPolicy.ENABLED.value,
        "capability_confirmation": "",
        "tool_trust_confirmation": "",
    }
    for key, default in defaults.items():
        if key not in llm:
            llm[key] = default
            changed = True
    if migrated.get("llm") != llm:
        changed = True
    migrated["llm"] = llm
    return migrated, changed


def _host_is_local_or_private(host: str) -> bool:
    normalized = host.strip("[]").lower()
    if normalized in {"localhost", "localhost.localdomain"} or normalized.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
        or address.is_multicast
        or address in ipaddress.ip_network("100.64.0.0/10")
    )


def validate_endpoint(
    provider: LLMProvider | str,
    api_base: str | None,
    endpoint_trust_mode: EndpointTrustMode | str | None = None,
) -> EndpointTrustMode:
    """Validate a base URL without performing network I/O.

    Remote endpoints must use HTTPS.  Local/private endpoints are allowed only
    when the profile explicitly opts into local endpoint trust.
    """
    normalized_provider = normalize_provider(provider)
    spec = provider_spec(normalized_provider)
    base = normalize_base_url(api_base)
    if isinstance(endpoint_trust_mode, EndpointTrustMode):
        mode = endpoint_trust_mode
    else:
        mode_value = str(endpoint_trust_mode or EndpointTrustMode.DEFAULT.value).lower()
        try:
            mode = EndpointTrustMode(mode_value)
        except ValueError as exc:
            raise ProfileValidationError(
                "invalid_endpoint_trust_mode",
                f"{spec.label} 的端点信任模式无效",
                field="endpoint_trust_mode",
            ) from exc

    if not base:
        if spec.requires_api_base:
            raise ProfileValidationError(
                "missing_api_base",
                f"{spec.label} 需要填写 Base URL",
                field="api_base",
            )
        return EndpointTrustMode.DEFAULT

    parsed = urlsplit(base)
    if not parsed.scheme or not parsed.netloc or parsed.username or parsed.password:
        raise ProfileValidationError(
            "invalid_api_base",
            f"{spec.label} 的 Base URL 格式无效，不能包含账号或密码",
            field="api_base",
        )
    if parsed.query or parsed.fragment:
        raise ProfileValidationError(
            "invalid_api_base",
            f"{spec.label} 的 Base URL 不能包含 query 或 fragment",
            field="api_base",
        )
    host = (parsed.hostname or "").lower()
    if _host_is_local_or_private(host):
        if mode is not EndpointTrustMode.LOCAL:
            raise ProfileValidationError(
                "endpoint_trust_required",
                f"{spec.label} 的本地或私有 Base URL 需要明确选择本地端点信任",
                field="endpoint_trust_mode",
            )
        if parsed.scheme.lower() not in {"https", "http"}:
            raise ProfileValidationError(
                "insecure_api_base",
                f"{spec.label} 的本地 Base URL 只支持 HTTP 或 HTTPS",
                field="api_base",
            )
        return mode

    if mode is EndpointTrustMode.LOCAL:
        raise ProfileValidationError(
            "invalid_endpoint_trust_mode",
            f"{spec.label} 的远程 Base URL 不能使用本地端点信任模式",
            field="endpoint_trust_mode",
        )
    if parsed.scheme.lower() != "https":
        raise ProfileValidationError(
            "insecure_api_base",
            f"{spec.label} 的远程 Base URL 必须使用 HTTPS",
            field="api_base",
        )
    return EndpointTrustMode.EXPLICIT


# Exact metadata for common chat models.  Unknown models stay unknown; the
# application never treats a missing provider capability record as support.
_KNOWN_SUPPORTED_MODELS: Mapping[LLMProvider, frozenset[str]] = {
    LLMProvider.DEEPSEEK: frozenset({"deepseek-chat", "deepseek-reasoner"}),
    LLMProvider.VOLCENGINE: frozenset(
        {"ark-code-latest", "doubao-seed-1-6-flash-250828"}
    ),
    LLMProvider.OPENAI_COMPATIBLE: frozenset(
        {"gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-3.5-turbo", "o1", "o3-mini"}
    ),
    LLMProvider.KIMI: frozenset(
        {"moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k", "kimi-k2-0711-preview"}
    ),
    LLMProvider.ZHIPU: frozenset({"glm-4", "glm-4-flash", "glm-4-plus", "glm-4.5"}),
    LLMProvider.QWEN: frozenset({"qwen-turbo", "qwen-plus", "qwen-max", "qwen-long"}),
}
_KNOWN_UNSUPPORTED_MARKERS = (
    "embedding",
    "rerank",
    "moderation",
    "whisper",
    "tts",
    "dall-e",
    "text-to-image",
)


@dataclass(frozen=True)
class CapabilityOverride:
    provider: LLMProvider
    model_name: str
    normalized_api_base: str
    tool_policy: ToolPolicy
    supported: bool


_CAPABILITY_OVERRIDES: list[CapabilityOverride] = []


def register_capability_override(
    provider: LLMProvider | str,
    model_name: str,
    supported: bool,
    *,
    api_base: str = "",
    tool_policy: ToolPolicy | str = ToolPolicy.ENABLED,
) -> None:
    """Register explicit metadata, primarily for provider integration tests."""
    _CAPABILITY_OVERRIDES.append(
        CapabilityOverride(
            normalize_provider(provider),
            str(model_name),
            normalize_base_url(api_base),
            ToolPolicy(str(tool_policy)),
            bool(supported),
        )
    )


def clear_capability_overrides() -> None:
    _CAPABILITY_OVERRIDES.clear()


def resolve_tool_capability(profile: LLMProfile) -> CapabilityDecision:
    if profile.tool_policy is ToolPolicy.DISABLED:
        return CapabilityDecision(
            CapabilityState.SUPPORTED,
            profile.provider,
            profile.model_name,
            "工具调用已由当前配置关闭",
        )

    for override in reversed(_CAPABILITY_OVERRIDES):
        if (
            override.provider is profile.provider
            and override.model_name == profile.model_name
            and override.normalized_api_base == profile.normalized_api_base
            and override.tool_policy is profile.tool_policy
        ):
            state = (
                CapabilityState.SUPPORTED
                if override.supported
                else CapabilityState.UNSUPPORTED
            )
            return CapabilityDecision(
                state,
                profile.provider,
                profile.model_name,
                "显式供应商能力元数据",
            )

    model = profile.model_name.strip().lower()
    if any(marker in model for marker in _KNOWN_UNSUPPORTED_MARKERS):
        return CapabilityDecision(
            CapabilityState.UNSUPPORTED,
            profile.provider,
            profile.model_name,
            "模型元数据明确不支持工具调用",
        )
    if model in _KNOWN_SUPPORTED_MODELS.get(profile.provider, frozenset()):
        return CapabilityDecision(
            CapabilityState.SUPPORTED,
            profile.provider,
            profile.model_name,
            "供应商内置能力元数据",
        )
    return CapabilityDecision(
        CapabilityState.UNKNOWN,
        profile.provider,
        profile.model_name,
        "缺少明确的工具调用能力元数据",
    )


def _profile_fingerprint_values(value: LLMProfile | Mapping[str, Any]) -> tuple[str, ...]:
    if isinstance(value, LLMProfile):
        provider = value.provider.value
        model_name = value.model_name
        api_base = value.normalized_api_base
        endpoint_trust_mode = value.endpoint_trust_mode.value
        tool_policy = value.tool_policy.value
    else:
        provider = normalize_provider(value.get("provider") or infer_provider(value.get("api_base"))).value
        model_name = str(value.get("model_name") or "").strip()
        api_base = normalize_base_url(value.get("api_base"))
        raw_mode = value.get("endpoint_trust_mode")
        mode = (
            raw_mode.value
            if isinstance(raw_mode, EndpointTrustMode)
            else str(raw_mode or EndpointTrustMode.DEFAULT.value).lower()
        )
        if api_base and mode == EndpointTrustMode.DEFAULT.value:
            mode = EndpointTrustMode.EXPLICIT.value
        endpoint_trust_mode = mode
        raw_tool_policy = value.get("tool_policy")
        tool_policy = (
            raw_tool_policy.value
            if isinstance(raw_tool_policy, ToolPolicy)
            else str(raw_tool_policy or ToolPolicy.ENABLED.value).lower()
        )
    return provider, model_name, api_base, endpoint_trust_mode, tool_policy


def capability_confirmation_for(value: LLMProfile | Mapping[str, Any]) -> str:
    """Return a non-secret fingerprint for capability and endpoint trust."""
    payload = "\x1f".join(_profile_fingerprint_values(value)).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _is_confirmation_for(profile: LLMProfile, confirmation: str) -> bool:
    return bool(confirmation) and hmac.compare_digest(
        confirmation, capability_confirmation_for(profile)
    )


def _endpoint_is_builtin_default(profile: LLMProfile) -> bool:
    if not profile.api_base:
        return True
    configured_host = (urlsplit(profile.api_base).hostname or "").lower()
    default_host = (urlsplit(provider_spec(profile.provider).default_api_base).hostname or "").lower()
    return bool(default_host and configured_host == default_host)


def requires_tool_trust_confirmation(profile: LLMProfile) -> bool:
    if profile.tool_policy is ToolPolicy.DISABLED or not profile.api_base:
        return False
    if profile.endpoint_trust_mode is EndpointTrustMode.LOCAL:
        return True
    return profile.provider is LLMProvider.OPENAI_COMPATIBLE or not _endpoint_is_builtin_default(profile)


def build_llm_profile(
    data: LLMProfile | Mapping[str, Any],
    *,
    require_api_key: bool = True,
    require_confirmation: bool = True,
) -> LLMProfile:
    """Validate one complete profile and enforce the capability gate."""
    if isinstance(data, LLMProfile):
        if require_api_key and not data.api_key:
            raise ProfileValidationError(
                "missing_api_key",
                f"{provider_spec(data.provider).label} 需要填写 API Key",
                field="api_key",
            )
        try:
            endpoint_mode = validate_endpoint(
                data.provider,
                data.api_base,
                data.endpoint_trust_mode,
            )
        except ProfileValidationError:
            raise
        profile = replace(data, endpoint_trust_mode=endpoint_mode)
    else:
        provider_value = data.get("provider") or infer_provider(data.get("api_base"))
        provider = normalize_provider(provider_value)
        model_name = str(data.get("model_name") or "").strip()
        api_key = str(data.get("api_key") or "")
        api_base = str(data.get("api_base") or "").strip()
        if not model_name:
            raise ProfileValidationError(
                "missing_model_name",
                f"{provider_spec(provider).label} 需要填写模型名称",
                field="model_name",
            )
        if require_api_key and not api_key:
            raise ProfileValidationError(
                "missing_api_key",
                f"{provider_spec(provider).label} 需要填写 API Key",
                field="api_key",
            )
        raw_mode = data.get("endpoint_trust_mode")
        mode_value = (
            raw_mode.value
            if isinstance(raw_mode, EndpointTrustMode)
            else str(raw_mode or EndpointTrustMode.DEFAULT.value).lower()
        )
        if api_base and mode_value == EndpointTrustMode.DEFAULT.value:
            mode_value = EndpointTrustMode.EXPLICIT.value
        try:
            endpoint_mode = validate_endpoint(provider, api_base, mode_value)
            raw_tool_policy = data.get("tool_policy")
            tool_policy = ToolPolicy(
                raw_tool_policy.value
                if isinstance(raw_tool_policy, ToolPolicy)
                else str(raw_tool_policy or ToolPolicy.ENABLED.value).lower()
            )
        except ValueError as exc:
            if isinstance(exc, ProfileValidationError):
                raise
            raise ProfileValidationError(
                "invalid_tool_policy",
                f"{provider_spec(provider).label} 的工具策略无效",
                field="tool_policy",
            ) from exc
        profile = LLMProfile(
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            api_base=api_base,
            endpoint_trust_mode=endpoint_mode,
            tool_policy=tool_policy,
            capability_confirmation=str(data.get("capability_confirmation") or ""),
            tool_trust_confirmation=str(data.get("tool_trust_confirmation") or ""),
        )

    decision = resolve_tool_capability(profile)
    if profile.tool_policy is ToolPolicy.ENABLED:
        if decision.state is CapabilityState.UNSUPPORTED:
            spec = provider_spec(profile.provider)
            raise ProfileValidationError(
                "unsupported_tool_capability",
                f"{spec.label} 模型 {profile.model_name} 明确不支持工具调用，请更换模型",
                field="model_name",
            )
        if require_confirmation and decision.state is CapabilityState.UNKNOWN and not _is_confirmation_for(
            profile, profile.capability_confirmation
        ):
            spec = provider_spec(profile.provider)
            raise ProfileValidationError(
                "capability_confirmation_required",
                f"{spec.label} 模型 {profile.model_name} 的工具调用能力未验证，请确认风险后再启用",
                field="capability_confirmation",
            )
        if require_confirmation and requires_tool_trust_confirmation(profile) and not _is_confirmation_for(
            profile, profile.tool_trust_confirmation
        ):
            spec = provider_spec(profile.provider)
            raise ProfileValidationError(
                "endpoint_tool_trust_required",
                f"{spec.label} 模型 {profile.model_name} 的自定义端点需要明确确认工具信任",
                field="tool_trust_confirmation",
            )
    return profile


def profile_to_dict(profile: LLMProfile) -> dict[str, Any]:
    return {
        "provider": profile.provider.value,
        "model_name": profile.model_name,
        "api_key": profile.api_key,
        "api_base": profile.api_base,
        "endpoint_trust_mode": profile.endpoint_trust_mode.value,
        "tool_policy": profile.tool_policy.value,
        "capability_confirmation": profile.capability_confirmation,
        "tool_trust_confirmation": profile.tool_trust_confirmation,
    }


__all__ = [
    "CapabilityDecision",
    "CapabilityState",
    "EndpointTrustMode",
    "LLMProfile",
    "LLMProvider",
    "ProfileValidationError",
    "ProviderSpec",
    "ToolPolicy",
    "build_llm_profile",
    "capability_confirmation_for",
    "clear_capability_overrides",
    "infer_provider",
    "normalize_base_url",
    "normalize_provider",
    "migrate_llm_config",
    "profile_to_dict",
    "provider_choices",
    "provider_spec",
    "register_capability_override",
    "requires_tool_trust_confirmation",
    "resolve_tool_capability",
    "validate_endpoint",
]
