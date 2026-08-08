"""LLM configuration validation and connection health checks."""

from __future__ import annotations

from typing import Any

from config import LLMConfig, get_active_llm_config


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
    if type(exc).__name__ in error_messages:
        return error_messages[type(exc).__name__]
    if isinstance(exc, (RuntimeError, ValueError)) and str(exc):
        return str(exc)
    return f"AI 服务请求失败（{type(exc).__name__}）。"


def validate_llm_config(llm_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a normalized, complete LLM configuration or raise ValueError."""
    config = dict(llm_config if llm_config is not None else get_active_llm_config())
    if not str(config.get("api_key", "")).strip():
        raise ValueError("尚未配置 LLM API Key，请先前往“设置”完成 AI 配置。")
    if not str(config.get("model_name", "")).strip():
        raise ValueError("尚未配置 LLM 模型名称，请先前往“设置”完成 AI 配置。")
    if not str(config.get("api_base", "")).strip():
        raise ValueError("尚未配置 API Base URL，请先前往“设置”完成 AI 配置。")
    return LLMConfig(**config).model_dump()


async def test_llm_connection(llm_config: dict[str, Any]) -> None:
    """Verify the configured URL, key, and model with a minimal API request."""
    # Lazy import avoids the custom package's compatibility exports loading
    # CustomerAgent while this shared service is still being initialized.
    from Agent.CustomerAgent.custom.llm_client import LLMClient

    client = LLMClient(
        api_key=llm_config["api_key"],
        api_base=llm_config["api_base"],
        model_name=llm_config["model_name"],
        temperature=0,
    )
    try:
        await client.initialize()
        await client.test_connection()
    finally:
        await client.close()
