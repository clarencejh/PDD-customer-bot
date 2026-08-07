"""
LLM 客户端模块

封装与 LLM API 的交互，提供类型安全的请求和响应处理。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from dataclasses import dataclass

try:
    from openai import AsyncOpenAI
except ImportError:
    raise ImportError("openai package is required: pip install openai>=1.109.1")

from utils.logger_loguru import get_logger
from utils.volcengine_models import ChatCompletionsRequest

logger = get_logger("LLMClient")


@dataclass
class LLMResponse:
    """LLM 响应封装"""
    content: Optional[str]
    tool_calls: Optional[List[Any]]
    raw_response: Any

    @property
    def has_tool_calls(self) -> bool:
        """是否有工具调用"""
        return self.tool_calls is not None and len(self.tool_calls) > 0


class LLMClient:
    """LLM 客户端封装"""

    def __init__(
        self,
        api_key: str,
        api_base: str,
        model_name: str,
        temperature: float,
        tools: Optional[List[Dict[str, Any]]] = None,
    ):
        """
        初始化 LLM 客户端

        Args:
            api_key: API 密钥
            api_base: API 基础地址
            model_name: 模型名称
            temperature: 温度参数
            tools: 可用工具列表
        """
        self.api_key = api_key
        self.api_base = api_base
        self.model_name = model_name
        self.temperature = temperature
        self.tools = tools or []

        self._client: Optional[AsyncOpenAI] = None

    async def initialize(self) -> None:
        """初始化 OpenAI 客户端"""
        self._client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.api_base or None,
            timeout=60.0,
        )
        logger.debug(f"LLM 客户端初始化成功: model={self.model_name}")

    async def close(self) -> None:
        """Close the underlying HTTP client and release its connection pool."""
        client = self._client
        self._client = None
        if client is None:
            return
        close = getattr(client, "close", None) or getattr(client, "aclose", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result

    async def test_connection(self) -> None:
        """Perform a minimal completion to validate URL, key and model together."""
        if not self._client:
            raise RuntimeError("LLM 客户端未初始化，请先调用 initialize()")

        response = await self._client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": "Reply with OK."}],
            temperature=0,
            max_tokens=1,
        )
        if not response.choices:
            raise RuntimeError("API 返回成功，但响应中没有可用结果")

    async def list_models(self) -> List[str]:
        """Return model IDs exposed by an OpenAI-compatible provider."""
        if not self._client:
            raise RuntimeError("LLM 客户端未初始化，请先调用 initialize()")
        page = await self._client.models.list()
        model_ids = {
            str(model.id).strip()
            for model in page.data
            if getattr(model, "id", None)
        }
        return sorted(model_ids, key=str.casefold)

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tool_choice: str = "auto",
    ) -> LLMResponse:
        """
        发送聊天请求到 LLM

        Args:
            messages: 消息列表
            tool_choice: 工具选择策略

        Returns:
            LLMResponse 封装的响应
        """
        if not self._client:
            raise RuntimeError("LLM 客户端未初始化，请先调用 initialize()")

        # 1. 构建请求参数字典
        request_dict: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
        }

        if self.tools:
            request_dict["tools"] = self.tools
            request_dict["tool_choice"] = tool_choice

        # 2. 使用 Pydantic 模型验证请求参数
        try:
            validated_request = ChatCompletionsRequest(**request_dict)
            logger.debug("请求参数验证通过")
        except Exception as e:
            logger.error(
                f"请求参数验证失败: error_type={type(e).__name__}"
            )
            raise

        # 3. 调试日志：输出发送给 LLM 的消息（限制内容长度，避免泄露敏感信息）
        logger.debug(f"发送给 LLM 的消息数: {len(messages)}")
        for i, msg in enumerate(messages):
            role = msg.get("role", "unknown")
            # 只记录消息角色和长度，不记录内容（避免泄露用户隐私）
            content = str(msg.get("content", ""))
            logger.debug(f"消息 {i} [{role}]: 长度={len(content)}")

        # 4. 调用 API
        response = await self._client.chat.completions.create(
            **validated_request.model_dump(exclude_none=True)
        )
        message = response.choices[0].message

        # 5. 记录 token 使用情况
        if response.usage:
            logger.debug(f"使用了 {response.usage.total_tokens} tokens "
                        f"(prompt: {response.usage.prompt_tokens}, "
                        f"completion: {response.usage.completion_tokens})")

        # 6. 调试日志：输出 LLM 的响应
        if message.tool_calls:
            tool_names = [tc.function.name for tc in message.tool_calls]
            logger.info(f"LLM 决定调用工具: {tool_names}")
        else:
            content_length = len(str(message.content or ""))
            logger.debug(f"LLM 直接回复已生成: length={content_length}")

        return LLMResponse(
            content=message.content,
            tool_calls=message.tool_calls,
            raw_response=response,
        )
