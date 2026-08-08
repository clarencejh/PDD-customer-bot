"""
配置文件管理模块
获取config.json中的配置，提供配置访问接口
提供类型安全、线程安全的配置管理系统
支持配置验证
"""
import json
import copy
import logging
import os
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Union
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from utils.runtime_path import get_config_path
from utils.secret_store import protect_secret, unprotect_secret

logger = logging.getLogger(__name__)


class ModelType(str, Enum):
    """模型类型枚举"""
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    GEMINI = "gemini"
    KIMI = "kimi"
    CLAUDE = "claude"

class LLMConfig(BaseModel):
    """LLM 配置模型"""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    model_name: str = Field(default="", description="模型名称")
    api_key: str = Field(default="", description="API密钥")
    api_base: str = Field(default="", description="API地址")

    @field_validator("model_name", "api_key")
    @classmethod
    def strip_llm_values(cls, value: str) -> str:
        return value.strip()

    @field_validator("api_base")
    @classmethod
    def validate_api_base(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return value

        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("API Base URL 必须是有效的 HTTP(S) 地址")
        if parsed.username or parsed.password:
            raise ValueError("API Base URL 不能包含用户名或密码")
        if parsed.query or parsed.fragment:
            raise ValueError("API Base URL 不能包含查询参数或片段")

        normalized_path = parsed.path.rstrip("/")
        return urlunsplit(
            (parsed.scheme.lower(), parsed.netloc, normalized_path, "", "")
        )


class LLMProviderConfig(LLMConfig):
    """Named OpenAI-compatible API provider configuration."""

    id: str = Field(min_length=1, description="供应商稳定标识")
    name: str = Field(min_length=1, description="供应商显示名称")

    @field_validator("id", "name")
    @classmethod
    def strip_provider_values(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("供应商标识和名称不能为空")
        return value


class BusinessHoursConfig(BaseModel):
    """营业时间配置模型"""
    start: str = Field(default="08:00", description="开始时间")
    end: str = Field(default="23:00", description="结束时间")

    @field_validator('start', 'end')
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        """验证时间格式 HH:MM"""
        try:
            datetime.strptime(v, '%H:%M')
            return v
        except ValueError:
            raise ValueError('时间格式必须为HH:MM，例如08:00')

class PromptConfig(BaseModel):
    """提示词配置模型"""
    instructions: list[str] = Field(default_factory=list, description="指令")


class ConfigModel(BaseModel):
    """配置模型"""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    business_hours: BusinessHoursConfig = Field(
        default_factory=BusinessHoursConfig,
        description="营业时间配置"
    )
    llm: LLMConfig = Field(
        default_factory=LLMConfig,
        description="LLM配置"
    )
    active_llm_provider: str = Field(default="", description="当前LLM供应商")
    llm_providers: list[LLMProviderConfig] = Field(
        default_factory=list,
        description="LLM供应商配置列表",
    )
    prompt: PromptConfig = Field(
        default_factory=PromptConfig,
        description="提示词配置"
    )
    auto_start_reply: bool = Field(
        default=True,
        description="软件启动后自动开启在线账号的自动回复",
    )
    launch_at_login: bool = Field(
        default=False,
        description="用户登录系统后自动启动软件",
    )
    system_notifications: bool = Field(
        default=True,
        description="启用系统托盘通知",
    )
    db_path: str = Field(default="./temp/channel_shop.db", description="数据库路径")

    @model_validator(mode="after")
    def validate_llm_providers(self):
        provider_ids = [provider.id for provider in self.llm_providers]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("LLM供应商标识不能重复")
        if self.active_llm_provider and self.active_llm_provider not in provider_ids:
            raise ValueError("当前LLM供应商不存在")
        return self



# 默认配置基础数据
config_base = {
    "business_hours": {
        "start": "08:00",
        "end": "23:00"
    },
    "db_path": "./temp/channel_shop.db",
    "llm": {
        "model_name": "",
        "api_key": "",
        "api_base": ""
    },
    "active_llm_provider": "default",
    "auto_start_reply": True,
    "launch_at_login": False,
    "system_notifications": True,
    "llm_providers": [
        {
            "id": "default",
            "name": "默认供应商",
            "model_name": "",
            "api_key": "",
            "api_base": ""
        }
    ],
    "prompt": {
        "instructions": [
            "1. 请用中文回复客户问题",
            "2. 当用户询问特定商品的信息、成分、使用方法、价格、规格等问题时，请优先使用 get_product_knowledge 工具获取商品详细知识，必须提供 goods_id（商品ID）和 shop_id（店铺ID）",
            "3. 当用户询问售后政策、物流信息、退换货规则、常见问题解答等非产品特定问题时，请使用 search_customer_service_knowledge 工具搜索客服知识，必须提供 query（搜索关键词）和 shop_id（店铺ID）",
            "4. 如果知识库中有相关信息，请根据知识库内容回答用户问题",
            "5. 如果知识库中没有相关信息，再根据已有知识回答或建议用户联系人工客服"
        ]
    }
}



class ConfigError(Exception):
    """配置相关错误的基类"""
    pass


class ConfigFileNotFoundError(ConfigError):
    """配置文件未找到错误"""
    pass


class ConfigParseError(ConfigError):
    """配置文件解析错误"""
    pass


class ConfigValidationError(ConfigError):
    """配置验证错误"""
    pass


class Config:
    """
    线程安全的配置管理器

    特性：
    - 类型安全的配置访问
    - 配置验证
    - 线程安全
    - 异常处理完善
    """

    def __init__(
        self,
        config_path: Union[str, Path, None] = None,
        auto_create: bool = True
    ):
        """
        初始化配置类

        Args:
            config_path: 配置文件路径
            auto_create: 是否自动创建默认配置文件
        """
        self.config_path = Path(config_path) if config_path else get_config_path()
        self.last_error: Optional[str] = None
        self._needs_secret_migration = False
        self.auto_create = auto_create

        # 线程安全锁
        self._lock = threading.RLock()

        # 配置缓存
        self._config: Optional[Dict[str, Any]] = None
        self._validated_config: Optional[ConfigModel] = None

        # 加载配置
        self.reload()

    def _load_config(self) -> Dict[str, Any]:
        """从文件加载配置"""
        if not self.config_path.exists():
            raise ConfigFileNotFoundError(f"配置文件不存在: {self.config_path}")

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                raw_config_data = json.load(f)

            self._needs_secret_migration = self._has_plaintext_secrets(raw_config_data)
            config_data = self._restore_secrets(raw_config_data)

            # 验证配置格式
            validated_config = ConfigModel(**config_data)
            self._validated_config = validated_config

            return config_data
        except json.JSONDecodeError as e:
            raise ConfigParseError(f"配置文件格式错误: {e}")
        except Exception as e:
            raise ConfigValidationError(f"配置验证失败: {e}")

    def _create_default_config_file(self) -> None:
        """创建默认配置文件"""
        try:
            # 创建目录（如果不存在）
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self._protect_secrets(config_base), f, ensure_ascii=False, indent=4)

            print(f"已创建默认配置文件：{self.config_path}")
        except Exception as e:
            raise ConfigError(f"创建配置文件失败: {e}")

    def reload(self) -> Dict[str, Any]:
        """重新加载配置文件"""
        with self._lock:
            try:
                self._config = self._load_config()
                self.last_error = None
                if os.name == "nt" and self._needs_secret_migration:
                    # Migrate legacy plaintext API keys on the next successful
                    # load; this is an atomic rewrite and preserves all fields.
                    self._needs_secret_migration = not self.save()
                return self._config
            except ConfigFileNotFoundError:
                if self.auto_create:
                    self._create_default_config_file()
                    self._config = copy.deepcopy(config_base)
                    self._validated_config = ConfigModel(**config_base)
                    return self._config
                else:
                    raise
            except Exception as e:
                self.last_error = str(e)
                logger.error(
                    f"configuration load failed; using safe defaults: "
                    f"error_type={type(e).__name__}"
                )
                # 使用默认配置
                self._config = copy.deepcopy(config_base)
                self._validated_config = ConfigModel(**config_base)
                return self._config

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置项，支持点号分隔的嵌套访问

        Args:
            key: 配置键名，支持嵌套访问如 'llm.api_key'
            default: 默认值

        Returns:
            配置值
        """
        with self._lock:
            if self._config is None:
                return default

            try:
                keys = key.split('.')
                value = self._config

                for k in keys:
                    if isinstance(value, dict) and k in value:
                        value = value[k]
                    else:
                        return default

                return value
            except Exception:
                return default

    def get_model(self) -> ConfigModel:
        """获取验证后的配置模型"""
        with self._lock:
            return self._validated_config or ConfigModel()

    def __getitem__(self, key: str) -> Any:
        """支持使用字典方式访问配置"""
        return self.get(key)

    def __contains__(self, key: str) -> bool:
        """支持使用 in 操作符检查配置项是否存在"""
        with self._lock:
            if self._config is None:
                return False
            keys = key.split('.')
            value = self._config
            for k in keys:
                if not isinstance(value, dict) or k not in value:
                    return False
                value = value[k]
            return True

    def set(self, key: str, value: Any, save: bool = True) -> Any:
        """
        设置配置项

        Args:
            key: 配置项键名
            value: 配置项值
            save: 是否立即保存到文件，默认为True

        Returns:
            设置的值
        """
        with self._lock:
            if self._config is None:
                self._config = copy.deepcopy(config_base)

            original_config = copy.deepcopy(self._config)
            original_validated = self._validated_config

            # 解析嵌套键
            keys = key.split('.')
            current = self._config

            # 导航到目标位置
            for k in keys[:-1]:
                if k not in current:
                    current[k] = {}
                current = current[k]

            # 设置值
            current[keys[-1]] = value

            # 重新验证配置
            try:
                self._validated_config = ConfigModel(**self._config)
                if save and not self.save():
                    raise ConfigError("配置文件写入失败")
            except Exception as e:
                self._config = original_config
                self._validated_config = original_validated
                raise ConfigValidationError(f"设置配置项失败: {e}")

            return value

    def update(self, config_dict: Dict[str, Any], save: bool = False) -> Dict[str, Any]:
        """
        批量更新配置

        Args:
            config_dict: 包含多个配置项的字典
            save: 是否立即保存到文件，默认为False

        Returns:
            更新后的完整配置
        """
        with self._lock:
            if self._config is None:
                self._config = copy.deepcopy(config_base)

            original_config = copy.deepcopy(self._config)
            original_validated = self._validated_config

            # 深度合并配置
            merged_config = self._deep_merge(self._config, config_dict)

            try:
                self._validated_config = ConfigModel(**merged_config)
                self._config = merged_config
                if save and not self.save():
                    raise ConfigError("配置文件写入失败")
                return self._config
            except Exception as e:
                self._config = original_config
                self._validated_config = original_validated
                raise ConfigValidationError(f"批量更新配置失败: {e}")

    def save(self) -> bool:
        """将当前配置原子性地保存到文件（临时文件+重命名）"""
        with self._lock:
            if self._config is None:
                raise ConfigError("没有可保存的配置")

            try:
                # 创建目录（如果不存在）
                self.config_path.parent.mkdir(parents=True, exist_ok=True)

                # 使用临时文件 + 原子重命名，避免写入过程中崩溃导致配置文件损坏
                temp_path = self.config_path.with_suffix('.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(
                        self._protect_secrets(self._config),
                        f,
                        ensure_ascii=False,
                        indent=4,
                    )

                # 原子重命名替换原文件
                temp_path.replace(self.config_path)
                return True
            except Exception as e:
                logger.error(
                    f"configuration save failed: error_type={type(e).__name__}"
                )
                # 清理临时文件（如果存在）
                try:
                    temp_path = self.config_path.with_suffix('.tmp')
                    if temp_path.exists():
                        temp_path.unlink()
                except Exception:
                    pass
                return False

    def _deep_merge(self, base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
        """深度合并字典"""
        result = base.copy()

        for key, value in update.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value

        return result

    @staticmethod
    def _protect_secrets(config_data: Dict[str, Any]) -> Dict[str, Any]:
        """Copy config and protect persisted API keys without changing memory."""
        result = copy.deepcopy(config_data)
        llm = result.get("llm")
        if isinstance(llm, dict) and "api_key" in llm:
            llm["api_key"] = protect_secret(llm.get("api_key"))
        providers = result.get("llm_providers")
        if isinstance(providers, list):
            for provider in providers:
                if isinstance(provider, dict) and "api_key" in provider:
                    provider["api_key"] = protect_secret(provider.get("api_key"))
        return result

    @staticmethod
    def _restore_secrets(config_data: Dict[str, Any]) -> Dict[str, Any]:
        """Copy config and decrypt values loaded from disk."""
        result = copy.deepcopy(config_data)
        llm = result.get("llm")
        if isinstance(llm, dict) and "api_key" in llm:
            llm["api_key"] = unprotect_secret(llm.get("api_key"))
        providers = result.get("llm_providers")
        if isinstance(providers, list):
            for provider in providers:
                if isinstance(provider, dict) and "api_key" in provider:
                    provider["api_key"] = unprotect_secret(provider.get("api_key"))
        return result

    @staticmethod
    def _has_plaintext_secrets(config_data: Dict[str, Any]) -> bool:
        llm = config_data.get("llm") if isinstance(config_data, dict) else None
        api_key = llm.get("api_key") if isinstance(llm, dict) else None
        if bool(api_key) and not str(api_key).startswith("dpapi:v1:"):
            return True
        providers = config_data.get("llm_providers", [])
        if isinstance(providers, list):
            return any(
                isinstance(provider, dict)
                and bool(provider.get("api_key"))
                and not str(provider.get("api_key")).startswith("dpapi:v1:")
                for provider in providers
            )
        return False

    @contextmanager
    def atomic_update(self):
        """原子性更新配置的上下文管理器"""
        import copy
        original_config = copy.deepcopy(self._config) if self._config else None
        original_validated = copy.deepcopy(self._validated_config)
        try:
            yield self
            if not self.save():
                raise ConfigError("配置文件写入失败")
        except Exception:
            # 回滚到原始配置
            if original_config is not None:
                self._config = original_config
                self._validated_config = original_validated
            raise

# 创建全局配置实例
config = Config()


# ==============================
# 便捷函数
# ==============================

def get_config(key: str, default: Any = None) -> Any:
    """全局便捷函数：获取配置项"""
    return config.get(key, default)


def set_config(key: str, value: Any, save: bool = False) -> Any:
    """全局便捷函数：设置配置项"""
    return config.set(key, value, save)


def reload_config() -> Dict[str, Any]:
    """全局便捷函数：重新加载配置"""
    return config.reload()


def save_config() -> bool:
    """全局便捷函数：保存配置"""
    return config.save()


def update_config(config_dict: Dict[str, Any], save: bool = False) -> Dict[str, Any]:
    """全局便捷函数：批量更新配置"""
    return config.update(config_dict, save)


def get_validated_config() -> ConfigModel:
    """全局便捷函数：获取验证后的配置模型"""
    return config.get_model()


def resolve_active_llm_config(config_data: Dict[str, Any]) -> Dict[str, str]:
    """Resolve the selected provider, falling back to the legacy llm object."""
    providers = config_data.get("llm_providers", [])
    active_id = config_data.get("active_llm_provider", "")
    if isinstance(providers, list) and providers:
        selected = next(
            (
                provider
                for provider in providers
                if isinstance(provider, dict) and provider.get("id") == active_id
            ),
            providers[0],
        )
        if isinstance(selected, dict):
            return {
                "model_name": str(selected.get("model_name", "")),
                "api_key": str(selected.get("api_key", "")),
                "api_base": str(selected.get("api_base", "")),
            }
    legacy = config_data.get("llm", {})
    return {
        "model_name": str(legacy.get("model_name", "")),
        "api_key": str(legacy.get("api_key", "")),
        "api_base": str(legacy.get("api_base", "")),
    }


def get_active_llm_config() -> Dict[str, str]:
    """Return the currently selected LLM provider configuration."""
    with config._lock:
        return resolve_active_llm_config(config._config or config_base)
