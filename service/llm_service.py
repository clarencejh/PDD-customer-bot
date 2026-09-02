"""LLM configuration validation and connection health checks."""

from __future__ import annotations

from typing import Any

from config import get_active_llm_config
from utils.llm_provider import (
    ProfileValidationError,
    build_llm_profile,
    profile_to_dict,
)


class LLMServiceError(RuntimeError):
    """An LLM failure that must be shown to the operator, not the customer."""


def llm_error_message(exc: Exception) -> str:
    """Convert provider exceptions into actionable operator-facing messages."""
    error_messages = {
        "AuthenticationError": "API Key 无效或已过期。",
        "PermissionDeniedError": "API Key 没有调用该模型的权限。",
        "NotFoundError": "API 地址、模型接口或模型名称不存在。",
        "BadRequestError": "请求被 API 拒绝，请检查模型名称和接口兼容性。",
        "APITimeoutError": "连接 API 超时，请检查网络和 API 地址。",
        "APIConnectionError": "无法连接 API，请检查网络、代理和 API 地址。",
        "RateLimitError": "API 已连接，但当前触发了限流或额度不足。",
    }
    if isinstance(exc, LLMServiceError) and str(exc):
        return str(exc)
    # 新统一传输层产生的安全错误：优先使用不泄露密钥/原始错误的 safe_message。
    safe_message = getattr(exc, "safe_message", None)
    if isinstance(safe_message, str) and safe_message:
        return safe_message
    if isinstance(exc, (ProfileValidationError, ValueError, RuntimeError)) and str(exc):
        return str(exc)
    if type(exc).__name__ in error_messages:
        return error_messages[type(exc).__name__]
    return f"AI 服务请求失败（{type(exc).__name__}）。"


def validate_llm_config(llm_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a validated profile dict or raise a provider-specific ValueError."""
    config_data = dict(
        llm_config if llm_config is not None else get_active_llm_config()
    )
    try:
        profile = build_llm_profile(
            config_data,
            require_api_key=True,
            require_confirmation=False,
        )
    except ProfileValidationError as exc:
        raise ValueError(exc.safe_message) from exc
    return profile_to_dict(profile)


async def test_llm_connection(llm_config: dict[str, Any]) -> None:
    """Verify the configured URL, key, and model with a minimal API request."""
    # Lazy import avoids the custom package's compatibility exports loading
    # CustomerAgent while this shared service is still being initialized.
    from Agent.CustomerAgent.custom.llm_client import LLMClient

    profile = build_llm_profile(
        llm_config,
        require_confirmation=False,
    )
    client = LLMClient(profile=profile, temperature=0)
    try:
        await client.initialize()
        await client.test_connection()
    finally:
        await client.close()
