"""
Agent 配置模块

管理 Agent 的默认配置和运行时配置参数。
"""
from typing import List, Optional
from dataclasses import dataclass, field

from config import get_active_llm_config, get_config
from utils.logger_loguru import get_logger
from utils.llm_provider import LLMProfile, build_llm_profile

logger = get_logger("AgentConfig")

# 默认参数
DEFAULT_DB_PATH = "./temp/channel_shop.db"
# Token 窗口大小：128k context，用于控制上下文长度
DEFAULT_TOKEN_WINDOW = 131072
# 压缩阈值比例：当历史消息超过 token_window * compress_ratio 时触发压缩
DEFAULT_COMPRESS_RATIO = 0.7
# 压缩时保留的最近消息条数
DEFAULT_RETAIN_COUNT = 10
# Agent 循环最大次数（防止无限工具调用）
DEFAULT_MAX_LOOPS = 5
# LLM 温度参数：0.0-2.0，值越高越随机，值越低越确定
DEFAULT_TEMPERATURE = 0.3


@dataclass
class AgentConfig:
    """Agent 配置数据类"""
    db_path: str = field(
        default_factory=lambda: get_config("db_path", DEFAULT_DB_PATH) or DEFAULT_DB_PATH
    )
    token_window: int = DEFAULT_TOKEN_WINDOW
    compress_ratio: float = DEFAULT_COMPRESS_RATIO
    retain_count: int = DEFAULT_RETAIN_COUNT
    max_loops: int = DEFAULT_MAX_LOOPS
    temperature: float = DEFAULT_TEMPERATURE

    # LLM 配置（来自当前选中的供应商，含显式供应商身份与信任/策略字段）
    provider: str = field(
        default_factory=lambda: get_active_llm_config().get("provider") or "openai_compatible"
    )
    model_name: str = field(
        default_factory=lambda: get_active_llm_config().get("model_name") or "gpt-3.5-turbo"
    )
    api_key: str = field(default_factory=lambda: get_active_llm_config().get("api_key", ""))
    api_base: str = field(default_factory=lambda: get_active_llm_config().get("api_base", ""))
    endpoint_trust_mode: str = field(
        default_factory=lambda: get_active_llm_config().get("endpoint_trust_mode", "default")
    )
    tool_policy: str = field(
        default_factory=lambda: get_active_llm_config().get("tool_policy", "enabled")
    )
    capability_confirmation: str = field(
        default_factory=lambda: get_active_llm_config().get("capability_confirmation", "")
    )
    tool_trust_confirmation: str = field(
        default_factory=lambda: get_active_llm_config().get("tool_trust_confirmation", "")
    )

    # Prompt 配置（仅 instructions 可配置，description 和 additional_context 由代码硬编码）
    instructions: List[str] = field(default_factory=lambda: get_config("prompt.instructions", []))

    @classmethod
    def load_from_config(cls) -> "AgentConfig":
        """从配置文件加载配置"""
        config = cls()
        logger.debug("Agent 配置加载完成")
        return config

    def validate(self) -> bool:
        """验证配置有效性"""
        try:
            self.profile
            return True
        except Exception as exc:
            logger.error(
                "LLM profile validation failed; "
                f"error_type={type(exc).__name__}"
            )
            return False

    @property
    def profile(self) -> LLMProfile:
        """Build an immutable validated snapshot for this agent instance."""
        return build_llm_profile(
            {
                "provider": self.provider,
                "model_name": self.model_name,
                "api_key": self.api_key,
                "api_base": self.api_base,
                "endpoint_trust_mode": self.endpoint_trust_mode,
                "tool_policy": self.tool_policy,
                "capability_confirmation": self.capability_confirmation,
                "tool_trust_confirmation": self.tool_trust_confirmation,
            }
        )
