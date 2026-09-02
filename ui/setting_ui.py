# 设置界面

import json
import os
import asyncio
import copy
import uuid
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QUrl
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QVBoxLayout, QWidget, QLabel,
                            QFormLayout, QGroupBox, QMessageBox, QDialog,
                            QListWidgetItem)
from PyQt6.QtGui import QDesktopServices, QFont
from qfluentwidgets import (CardWidget, SubtitleLabel, CaptionLabel, BodyLabel,
                           PrimaryPushButton, PushButton, StrongBodyLabel,
                           LineEdit, ComboBox, ScrollArea, FluentIcon as FIF,
                           InfoBar, InfoBarPosition, TextEdit, PasswordLineEdit,
                           TimePicker, ListWidget, EditableComboBox, SwitchButton)
from PyQt6.QtCore import QTime
from utils.logger_loguru import get_logger
from config import LLMConfig, LLMProviderConfig, config, config_base
from utils.llm_provider import (
    CapabilityState,
    ProfileValidationError,
    build_llm_profile,
    capability_confirmation_for,
    profile_to_dict,
    provider_choices,
    provider_spec,
    resolve_tool_capability,
    requires_tool_trust_confirmation,
)
from Agent.CustomerAgent.custom.llm_client import LLMClient
from service.llm_service import llm_error_message
from service.data_maintenance_service import data_maintenance_service
from service.startup_service import startup_service
from service.system_notification_service import get_system_notifier


def _llm_error_message(exc: Exception) -> str:
    return llm_error_message(exc)


class LLMConnectionTestThread(QThread):
    """Validate an LLM endpoint without blocking the settings UI."""

    test_finished = pyqtSignal(bool, str)

    def __init__(self, llm_config: dict, parent=None):
        super().__init__(parent)
        self.llm_config = llm_config

    def run(self):
        try:
            asyncio.run(self._test())
            self.test_finished.emit(True, "API 地址、密钥和模型均可正常调用。")
        except Exception as exc:
            self.test_finished.emit(False, _llm_error_message(exc))

    async def _test(self):
        client = None
        try:
            profile = build_llm_profile(
                self.llm_config,
                require_confirmation=False,
            )
            client = LLMClient(profile=profile, temperature=0)
            await client.initialize()
            await client.test_connection()
        finally:
            if client is not None:
                try:
                    await client.close()
                except Exception:
                    pass


class MaintenanceWorker(QThread):
    """Run filesystem/database cleanup without blocking the settings UI."""

    task_finished = pyqtSignal(str, object)
    task_failed = pyqtSignal(str, str)

    def __init__(self, action: str, callback, parent=None):
        super().__init__(parent)
        self.action = action
        self.callback = callback

    def run(self):
        try:
            self.task_finished.emit(self.action, self.callback())
        except Exception as exc:
            self.task_failed.emit(self.action, str(exc))


class LLMBatchTestThread(QThread):
    """Test several providers without blocking the UI."""

    test_finished = pyqtSignal(object)

    def __init__(self, providers: list[dict], parent=None):
        super().__init__(parent)
        self.providers = providers

    def run(self):
        self.test_finished.emit(asyncio.run(self._test_all()))

    async def _test_all(self) -> dict:
        async def test_provider(provider: dict):
            client = None
            try:
                profile = build_llm_profile(
                    provider,
                    require_confirmation=False,
                )
                client = LLMClient(profile=profile, temperature=0)
                await client.initialize()
                await client.test_connection()
                return provider["id"], (True, "连接正常")
            except Exception as exc:
                return provider["id"], (False, _llm_error_message(exc))
            finally:
                if client is not None:
                    try:
                        await client.close()
                    except Exception:
                        pass

        results = await asyncio.gather(
            *(test_provider(provider) for provider in self.providers)
        )
        return dict(results)


class LLMModelFetchThread(QThread):
    """Fetch provider model IDs in the background."""

    fetch_finished = pyqtSignal(bool, object, str)

    def __init__(self, llm_config: dict, parent=None):
        super().__init__(parent)
        self.llm_config = llm_config

    def run(self):
        try:
            models = asyncio.run(self._fetch())
            if not models:
                raise RuntimeError("供应商未返回任何模型")
            self.fetch_finished.emit(True, models, f"已拉取 {len(models)} 个模型。")
        except Exception as exc:
            self.fetch_finished.emit(False, [], _llm_error_message(exc))

    async def _fetch(self):
        client = None
        try:
            profile = build_llm_profile(
                self.llm_config,
                require_confirmation=False,
            )
            client = LLMClient(profile=profile, temperature=0)
            await client.initialize()
            return await client.list_models()
        finally:
            if client is not None:
                try:
                    await client.close()
                except Exception:
                    pass


class AddLLMProviderDialog(QDialog):
    """Dialog for creating a provider record."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加供应商")
        self.setModal(True)
        self.resize(520, 320)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(12)
        self.name_edit = LineEdit()
        self.name_edit.setPlaceholderText("供应商名称")
        self.provider_combo = ComboBox()
        self._provider_values = []
        for provider_value, label in provider_choices():
            self.provider_combo.addItem(label)
            self._provider_values.append(provider_value)
        self.api_base_edit = LineEdit()
        self.api_base_edit.setPlaceholderText("https://api.deepseek.com")
        self.endpoint_trust_combo = ComboBox()
        self._endpoint_trust_values = ["default", "explicit", "local"]
        self.endpoint_trust_combo.addItems(
            ["供应商默认/远程 HTTPS", "自定义远程 HTTPS", "明确允许本地或私有端点"]
        )
        self.api_key_edit = PasswordLineEdit()
        self.api_key_edit.setPlaceholderText("API Key")
        self.model_edit = LineEdit()
        self.model_edit.setPlaceholderText("可稍后拉取或手动输入")
        form.addRow("供应商名称:", self.name_edit)
        form.addRow("模型供应商:", self.provider_combo)
        form.addRow("API Base URL:", self.api_base_edit)
        form.addRow("端点信任:", self.endpoint_trust_combo)
        form.addRow("API Key:", self.api_key_edit)
        form.addRow("模型名称:", self.model_edit)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_btn = PushButton("取消")
        confirm_btn = PrimaryPushButton("添加")
        cancel_btn.clicked.connect(self.reject)
        confirm_btn.clicked.connect(self._acceptIfValid)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(confirm_btn)
        layout.addLayout(buttons)

    def _acceptIfValid(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "输入错误", "供应商名称不能为空。")
            return
        try:
            LLMConfig(
                provider=self._provider_values[self.provider_combo.currentIndex()],
                api_base=self.api_base_edit.text().strip(),
                api_key=self.api_key_edit.text().strip(),
                model_name=self.model_edit.text().strip(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "输入错误", str(exc))
            return
        self.accept()

    def providerData(self) -> dict:
        return {
            "id": uuid.uuid4().hex,
            "name": self.name_edit.text().strip(),
            "provider": self._provider_values[self.provider_combo.currentIndex()],
            "api_base": self.api_base_edit.text().strip(),
            "endpoint_trust_mode": self._endpoint_trust_values[
                self.endpoint_trust_combo.currentIndex()
            ],
            "api_key": self.api_key_edit.text().strip(),
            "model_name": self.model_edit.text().strip(),
            "tool_policy": "enabled",
            "capability_confirmation": "",
            "tool_trust_confirmation": "",
        }




class LLMConfigCard(CardWidget):
    """供应商识别与兼容的 LLM 配置卡片。"""

    DEFAULT_MODELS = {
        "deepseek": "deepseek-chat",
        "volcengine": "doubao-seed-1-6-flash-250828",
        "openai_compatible": "",
        "kimi": "moonshot-v1-8k",
        "zhipu": "glm-4-flash",
        "qwen": "qwen-plus",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.providers = []
        self.provider_status = {}
        self._current_provider_id = None
        self._loading_provider = False
        self._profile_meta = {
            "endpoint_trust_mode": "default",
            "tool_policy": "enabled",
            "capability_confirmation": "",
            "tool_trust_confirmation": "",
        }
        self.setupUI()

    def setupUI(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        # 卡片标题
        title_label = StrongBodyLabel("LLM模型配置")
        title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)

        provider_workspace = QHBoxLayout()
        provider_workspace.setSpacing(18)

        list_panel = QWidget()
        list_panel.setFixedWidth(230)
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(8)
        list_layout.addWidget(BodyLabel("供应商列表"))
        self.provider_list = ListWidget()
        self.provider_list.setMinimumHeight(260)
        list_layout.addWidget(self.provider_list, 1)

        list_buttons = QHBoxLayout()
        self.add_provider_btn = PushButton("添加")
        self.add_provider_btn.setIcon(FIF.ADD)
        self.delete_provider_btn = PushButton("删除")
        self.delete_provider_btn.setIcon(FIF.DELETE)
        list_buttons.addWidget(self.add_provider_btn)
        list_buttons.addWidget(self.delete_provider_btn)
        list_layout.addLayout(list_buttons)
        self.batch_test_btn = PushButton("批量测试")
        self.batch_test_btn.setIcon(FIF.SYNC)
        list_layout.addWidget(self.batch_test_btn)

        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(12)
        detail_layout.addWidget(BodyLabel("当前供应商配置"))

        provider_workspace.addWidget(list_panel)
        provider_workspace.addWidget(detail_panel, 1)
        layout.addLayout(provider_workspace)

        # 表单布局
        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft)

        self.provider_name_edit = LineEdit()
        self.provider_name_edit.setPlaceholderText("输入供应商名称")
        form_layout.addRow("供应商名称:", self.provider_name_edit)

        # 模型供应商身份（显式注册表，不再靠 URL 猜测）
        self.provider_combo = ComboBox()
        self.provider_combo.setAccessibleName("LLM provider")
        self._provider_values = []
        for provider_value, label in provider_choices():
            self.provider_combo.addItem(label)
            self._provider_values.append(provider_value)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form_layout.addRow("模型供应商:", self.provider_combo)

        # API Base URL
        self.api_base_edit = LineEdit()
        self.api_base_edit.setAccessibleName("LLM Base URL")
        form_layout.addRow("API Base URL:", self.api_base_edit)

        # 端点信任模式
        self.endpoint_trust_combo = ComboBox()
        self.endpoint_trust_combo.setAccessibleName("LLM endpoint trust mode")
        self._endpoint_trust_values = ["default", "explicit", "local"]
        self.endpoint_trust_combo.addItems(
            ["供应商默认/远程 HTTPS", "自定义远程 HTTPS", "明确允许本地或私有端点"]
        )
        form_layout.addRow("端点信任:", self.endpoint_trust_combo)

        # API Key
        self.api_key_edit = PasswordLineEdit()
        self.api_key_edit.setPlaceholderText("输入您的 API Key")
        form_layout.addRow("API Key:", self.api_key_edit)

        # Model Name
        self.model_name_edit = EditableComboBox()
        self.model_name_edit.setAccessibleName("LLM model name")
        self.model_name_edit.setPlaceholderText("输入模型名称，如：doubao-seed-1-6-flash-250828")
        form_layout.addRow("模型名称:", self.model_name_edit)

        detail_layout.addLayout(form_layout)

        action_row = QHBoxLayout()
        self.reset_provider_default_btn = PushButton("恢复供应商默认")
        self.reset_provider_default_btn.clicked.connect(self.reset_to_provider_default)
        action_row.addWidget(self.reset_provider_default_btn)
        action_row.addStretch()
        detail_layout.addLayout(action_row)

        # 状态标签（能力/端点信任校验结果）
        self.status_label = CaptionLabel("")
        self.status_label.setAccessibleName("LLM validation status")
        self.status_label.setStyleSheet("color: #666; padding: 4px 0;")
        detail_layout.addWidget(self.status_label)

        # 说明文本
        description_label = CaptionLabel(
            "供应商通过 LiteLLM 直接路由；OpenAI-compatible 可填写任意兼容模型和 Base URL。\n"
            "自定义或本地端点需要明确信任确认，保存时才会生效。"
        )
        description_label.setStyleSheet("color: #666; padding: 8px 0;")
        detail_layout.addWidget(description_label)

        action_layout = QHBoxLayout()
        action_layout.addStretch()
        self.fetch_models_btn = PushButton("拉取模型")
        self.fetch_models_btn.setIcon(FIF.DOWNLOAD)
        self.test_btn = PushButton("测试连接")
        self.test_btn.setIcon(FIF.SYNC)
        action_layout.addWidget(self.fetch_models_btn)
        action_layout.addWidget(self.test_btn)
        detail_layout.addLayout(action_layout)

        self.provider_list.currentRowChanged.connect(self._onProviderChanged)
        self.provider_name_edit.editingFinished.connect(self._onProviderNameEdited)
        self.add_provider_btn.clicked.connect(self.addProvider)
        self.delete_provider_btn.clicked.connect(self.deleteCurrentProvider)

    def getConfig(self) -> dict:
        """获取配置（当前供应商条目，含显式身份与信任/策略字段）"""
        self._storeCurrentProvider()
        provider_idx = self.provider_combo.currentIndex()
        return {
            "provider": self._provider_values[provider_idx],
            "api_base": self.api_base_edit.text().strip(),
            "endpoint_trust_mode": self._endpoint_trust_values[
                self.endpoint_trust_combo.currentIndex()
            ],
            "api_key": self.api_key_edit.text().strip(),
            "model_name": self.model_name_edit.currentText().strip(),
            **self._profile_meta,
        }

    def setConfig(self, config: dict):
        """设置配置"""
        provider = str(config.get("provider", "openai_compatible"))
        if provider in self._provider_values:
            self.provider_combo.setCurrentIndex(self._provider_values.index(provider))
        self.api_base_edit.setText(config.get("api_base", ""))
        trust_mode = str(config.get("endpoint_trust_mode", "default"))
        if trust_mode in self._endpoint_trust_values:
            self.endpoint_trust_combo.setCurrentIndex(
                self._endpoint_trust_values.index(trust_mode)
            )
        self.api_key_edit.setText(config.get("api_key", ""))
        self.model_name_edit.clear()
        model_name = config.get("model_name", "")
        if model_name:
            self.model_name_edit.addItem(model_name)
        self.model_name_edit.setCurrentText(model_name)
        for key in self._profile_meta:
            if key in config:
                self._profile_meta[key] = config[key]
        self._on_provider_changed(self.provider_combo.currentIndex())

    def _on_provider_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._provider_values):
            return
        spec = provider_spec(self._provider_values[index])
        self.api_base_edit.setPlaceholderText(
            spec.default_api_base or "https://your-openai-compatible-host/v1"
        )
        self.model_name_edit.setPlaceholderText(
            self.DEFAULT_MODELS.get(spec.provider.value) or "输入任意兼容模型名称"
        )
        if spec.requires_api_base:
            self.status_label.setText("OpenAI-compatible 必须填写 Base URL")
        elif spec.default_api_base:
            self.status_label.setText(
                f"默认端点：{spec.default_api_base}（可填写自定义覆盖）"
            )
        else:
            self.status_label.setText("")

    def reset_to_provider_default(self) -> None:
        """将端点与模型指导恢复为当前供应商默认值（不改动密钥）。"""
        provider = self._provider_values[self.provider_combo.currentIndex()]
        spec = provider_spec(provider)
        self.api_base_edit.setText(spec.default_api_base)
        self.model_name_edit.clear()
        if self.DEFAULT_MODELS.get(provider):
            self.model_name_edit.addItem(self.DEFAULT_MODELS[provider])
            self.model_name_edit.setCurrentText(self.DEFAULT_MODELS[provider])
        self._on_provider_changed(self.provider_combo.currentIndex())

    def setProviders(self, providers: list, active_provider_id: str = ""):
        """Load provider records and select the active one."""
        if not providers:
            providers = [{
                "id": "default",
                "name": "默认供应商",
                "api_base": "https://ark.cn-beijing.volces.com/api/v3",
                "api_key": "",
                "model_name": "",
            }]
        self.providers = copy.deepcopy(providers)
        selected_index = 0
        for index, provider in enumerate(self.providers):
            provider_id = str(provider.get("id") or uuid.uuid4().hex)
            provider["id"] = provider_id
            provider["name"] = str(provider.get("name") or f"供应商 {index + 1}")
            if provider_id == active_provider_id:
                selected_index = index
        self._refreshProviderList(selected_index)
        self._loadProvider(selected_index)
        self._updateDeleteButton()

    def getProviders(self) -> tuple[list, str]:
        self._storeCurrentProvider()
        current_item = self.provider_list.currentItem()
        active_id = (
            current_item.data(Qt.ItemDataRole.UserRole)
            if current_item is not None
            else self._current_provider_id
        )
        return copy.deepcopy(self.providers), str(active_id or "")

    def addProvider(self):
        self._storeCurrentProvider()
        dialog = AddLLMProviderDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        provider = dialog.providerData()
        self.providers.append(provider)
        self._refreshProviderList(len(self.providers) - 1)
        self._loadProvider(len(self.providers) - 1)
        self._updateDeleteButton()

    def deleteCurrentProvider(self):
        if len(self.providers) <= 1:
            QMessageBox.warning(self, "无法删除", "至少需要保留一个供应商。")
            return
        index = self.provider_list.currentRow()
        if index < 0:
            return
        provider_name = self.providers[index].get("name", "当前供应商")
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定删除供应商 '{provider_name}' 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.providers.pop(index)
        next_index = min(index, len(self.providers) - 1)
        self.setProviders(self.providers, self.providers[next_index]["id"])

    def _onProviderChanged(self, index: int):
        if self._loading_provider or index < 0:
            return
        self._storeCurrentProvider()
        self._loadProvider(index)

    def _onProviderNameEdited(self):
        self._storeCurrentProvider()
        self._refreshProviderList(self.provider_list.currentRow())

    def _storeCurrentProvider(self):
        if not self._current_provider_id:
            return
        provider = next(
            (item for item in self.providers if item.get("id") == self._current_provider_id),
            None,
        )
        if provider is None:
            return
        provider_idx = self.provider_combo.currentIndex()
        provider.update({
            "name": self.provider_name_edit.text().strip() or provider.get("name", "供应商"),
            "provider": self._provider_values[provider_idx],
            "api_base": self.api_base_edit.text().strip(),
            "endpoint_trust_mode": self._endpoint_trust_values[
                self.endpoint_trust_combo.currentIndex()
            ],
            "api_key": self.api_key_edit.text().strip(),
            "model_name": self.model_name_edit.currentText().strip(),
            "tool_policy": self._profile_meta.get("tool_policy", "enabled"),
            "capability_confirmation": self._profile_meta.get("capability_confirmation", ""),
            "tool_trust_confirmation": self._profile_meta.get("tool_trust_confirmation", ""),
        })

    def _loadProvider(self, index: int):
        if not 0 <= index < len(self.providers):
            return
        provider = self.providers[index]
        self._current_provider_id = provider["id"]
        self.provider_name_edit.setText(provider.get("name", ""))
        self.setConfig(provider)


    def _updateDeleteButton(self):
        self.delete_provider_btn.setEnabled(len(self.providers) > 1)

    def _refreshProviderList(self, selected_index: int | None = None):
        if selected_index is None:
            selected_index = self.provider_list.currentRow()
        self._loading_provider = True
        self.provider_list.clear()
        for provider in self.providers:
            status = self.provider_status.get(provider["id"])
            status_text = "未测试"
            if status is not None:
                status_text = "通过" if status[0] else "失败"
            item = QListWidgetItem(f"{provider['name']}  ·  {status_text}")
            item.setData(Qt.ItemDataRole.UserRole, provider["id"])
            item.setToolTip(status[1] if status else provider["name"])
            self.provider_list.addItem(item)
        if self.providers:
            self.provider_list.setCurrentRow(
                max(0, min(selected_index, len(self.providers) - 1))
            )
        self._loading_provider = False

    def setProviderStatus(self, provider_id: str, success: bool, message: str):
        self.provider_status[provider_id] = (success, message)
        self._refreshProviderList(self.provider_list.currentRow())

    def setModelOptions(self, models: list[str]):
        current_model = self.model_name_edit.currentText().strip()
        self.model_name_edit.clear()
        for model in models:
            self.model_name_edit.addItem(model)
        if current_model:
            self.model_name_edit.setCurrentText(current_model)
        elif models:
            self.model_name_edit.setCurrentIndex(0)

    def setActionsEnabled(self, enabled: bool):
        self.provider_list.setEnabled(enabled)
        for button in (
            self.test_btn,
            self.batch_test_btn,
            self.fetch_models_btn,
            self.add_provider_btn,
            self.delete_provider_btn,
        ):
            button.setEnabled(enabled)
        if enabled:
            self._updateDeleteButton()


def inspect_llm_draft(config_data: dict) -> dict:
    """Headless validation state used by the UI and its policy tests."""
    try:
        profile = build_llm_profile(
            config_data,
            require_confirmation=False,
        )
    except ProfileValidationError as exc:
        state = "unsupported" if exc.code == "unsupported_tool_capability" else "invalid"
        return {
            "state": state,
            "error": exc,
            "profile": None,
            "fingerprint": "",
            "requires_confirmation": False,
            "requires_tool_trust": False,
        }

    decision = resolve_tool_capability(profile)
    fingerprint = capability_confirmation_for(profile)
    capability_confirmed = config_data.get("capability_confirmation") == fingerprint
    tool_trust_required = requires_tool_trust_confirmation(profile)
    tool_trust_confirmed = config_data.get("tool_trust_confirmation") == fingerprint
    requires_confirmation = (
        decision.state is CapabilityState.UNKNOWN and not capability_confirmed
    ) or (tool_trust_required and not tool_trust_confirmed)
    return {
        "state": decision.state.value,
        "error": None,
        "profile": profile,
        "decision": decision,
        "fingerprint": fingerprint,
        "requires_confirmation": requires_confirmation,
        "requires_tool_trust": tool_trust_required and not tool_trust_confirmed,
    }


class PromptConfigCard(CardWidget):
    """提示词配置卡片"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUI()

    def setupUI(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        # 卡片标题
        title_label = StrongBodyLabel("AI提示词配置")
        title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)

        # 表单布局
        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft)

        # 行为指令（用户唯一可配置的字段）
        self.instructions_edit = TextEdit()
        self.instructions_edit.setPlaceholderText("输入行为指令，每行一条")
        self.instructions_edit.setMaximumHeight(200)
        form_layout.addRow("行为指令:", self.instructions_edit)

        layout.addLayout(form_layout)

        # 说明文本
        description_label = CaptionLabel(
            "配置AI助手的行为指令。\n"
            "角色描述和工具说明由系统自动管理，无需手动配置。"
        )
        description_label.setStyleSheet("color: #666; padding: 8px 0;")
        layout.addWidget(description_label)

    def getConfig(self) -> dict:
        """获取配置"""
        return {
            "instructions": [
                line.strip() for line in self.instructions_edit.toPlainText().splitlines() if line.strip()
            ]
        }

    def setConfig(self, config: dict):
        """设置配置"""
        instructions = config.get("instructions", [])
        if isinstance(instructions, list):
            self.instructions_edit.setPlainText("\n".join(instructions))
        elif isinstance(instructions, str):
            self.instructions_edit.setPlainText(instructions)


class BusinessHoursCard(CardWidget):
    """业务时间配置卡片"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUI()

    def setupUI(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        # 卡片标题
        title_label = StrongBodyLabel("业务时间设置")
        title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)

        # 表单布局
        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft)

        # 开始时间
        self.start_time_picker = TimePicker()
        self.start_time_picker.setTime(QTime(8, 0))  # 默认8:00
        form_layout.addRow("开始时间:", self.start_time_picker)

        # 结束时间
        self.end_time_picker = TimePicker()
        self.end_time_picker.setTime(QTime(23, 0))  # 默认23:00
        form_layout.addRow("结束时间:", self.end_time_picker)

        self.auto_start_reply_switch = SwitchButton()
        self.auto_start_reply_switch.setChecked(True)
        form_layout.addRow("启动时自动开启回复:", self.auto_start_reply_switch)

        layout.addLayout(form_layout)

        # 说明文本
        description_label = CaptionLabel(
            "设置AI客服的工作时间。在工作时间内，系统将自动响应客户消息。\n"
            "在非工作时间，系统将不会自动回复。"
        )
        description_label.setStyleSheet("color: #666; padding: 8px 0;")
        layout.addWidget(description_label)

    def getConfig(self) -> dict:
        """获取配置"""
        return {
            "businessHours": {
                "start": self.start_time_picker.getTime().toString("HH:mm"),
                "end": self.end_time_picker.getTime().toString("HH:mm")
            },
            "business_hours": {
                "start": self.start_time_picker.getTime().toString("HH:mm"),
                "end": self.end_time_picker.getTime().toString("HH:mm")
            },
            "auto_start_reply": self.auto_start_reply_switch.isChecked(),
        }

    def setConfig(self, config: dict):
        """设置配置"""
        # 支持新旧配置格式
        business_hours = config.get("businessHours", config.get("business_hours", {}))

        # 解析开始时间
        start_time_str = business_hours.get("start", "08:00")
        start_time = QTime.fromString(start_time_str, "HH:mm")
        if start_time.isValid():
            self.start_time_picker.setTime(start_time)

        # 解析结束时间
        end_time_str = business_hours.get("end", "23:00")
        end_time = QTime.fromString(end_time_str, "HH:mm")
        if end_time.isValid():
            self.end_time_picker.setTime(end_time)
        self.auto_start_reply_switch.setChecked(config.get("auto_start_reply", True))


class SystemBehaviorCard(CardWidget):
    """系统启动与通知设置。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        title_label = StrongBodyLabel("系统行为")
        title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)

        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.launch_at_login_switch = SwitchButton()
        self.system_notifications_switch = SwitchButton()
        self.system_notifications_switch.setChecked(True)
        form_layout.addRow("登录系统后自动启动:", self.launch_at_login_switch)
        form_layout.addRow("启用系统通知:", self.system_notifications_switch)
        layout.addLayout(form_layout)

    def getConfig(self) -> dict:
        return {
            "launch_at_login": self.launch_at_login_switch.isChecked(),
            "system_notifications": self.system_notifications_switch.isChecked(),
        }

    def setConfig(self, values: dict) -> None:
        self.launch_at_login_switch.setChecked(values.get("launch_at_login", False))
        self.system_notifications_switch.setChecked(
            values.get("system_notifications", True)
        )


class DataManagementCard(CardWidget):
    """运行数据位置与清理入口。"""

    def __init__(self, data_path: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        title_label = StrongBodyLabel("数据管理")
        title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)

        self.path_edit = LineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setText(data_path)
        layout.addWidget(self.path_edit)

        description = CaptionLabel(
            "配置、账号登录态、知识库和聊天记录保存在此目录；清理缓存和日志不会删除这些数据。"
        )
        description.setStyleSheet("color: #667085;")
        description.setWordWrap(True)
        layout.addWidget(description)

        actions = QHBoxLayout()
        self.open_directory_btn = PushButton("打开数据目录")
        self.open_directory_btn.setIcon(FIF.FOLDER)
        self.clear_cache_btn = PushButton("清理缓存和日志")
        self.clear_cache_btn.setIcon(FIF.BROOM)
        self.clear_history_btn = PushButton("清空聊天记录")
        self.clear_history_btn.setIcon(FIF.DELETE)
        actions.addWidget(self.open_directory_btn)
        actions.addWidget(self.clear_cache_btn)
        actions.addWidget(self.clear_history_btn)
        actions.addStretch()
        layout.addLayout(actions)

    def setActionsEnabled(self, enabled: bool) -> None:
        self.open_directory_btn.setEnabled(enabled)
        self.clear_cache_btn.setEnabled(enabled)
        self.clear_history_btn.setEnabled(enabled)


class SettingUI(QFrame):
    """设置界面"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.logger = get_logger("SettingUI")
        self.connection_test_thread = None
        self.batch_test_thread = None
        self.model_fetch_thread = None
        self.maintenance_worker = None
        self._task_provider_id = None
        self._batch_initial_results = {}
        self.setupUI()
        self.loadConfig()

        # 设置对象名
        self.setObjectName("设置")

    def closeEvent(self, event):
        # 维护任务在后台运行，不在窗口关闭事件中无限等待。
        super().closeEvent(event)

    def setupUI(self):
        """设置主界面UI"""
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(25)

        # 创建头部区域
        header_widget = self.createHeaderWidget()

        # 创建内容区域
        content_widget = self.createContentWidget()

        # 连接按钮信号
        self.save_btn.clicked.connect(self.onSaveConfig)
        self.reset_btn.clicked.connect(self.onResetConfig)
        self.llm_config_card.test_btn.clicked.connect(self.onTestConnection)
        self.llm_config_card.batch_test_btn.clicked.connect(self.onBatchTestConnections)
        self.llm_config_card.fetch_models_btn.clicked.connect(self.onFetchModels)
        self.data_management_card.open_directory_btn.clicked.connect(
            self.openDataDirectory
        )
        self.data_management_card.clear_cache_btn.clicked.connect(
            self.clearCacheAndLogs
        )
        self.data_management_card.clear_history_btn.clicked.connect(
            self.clearConversationHistory
        )

        # 添加到主布局
        main_layout.addWidget(header_widget)
        main_layout.addWidget(content_widget, 1)

    def createHeaderWidget(self):
        """创建头部区域"""
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(20)

        # 标题
        title_label = SubtitleLabel("系统设置")
        title_label.setFont(QFont("Microsoft YaHei", 18, QFont.Weight.Bold))

        # 描述
        description_label = CaptionLabel("配置AI客服的基本参数和工作时间")
        description_label.setStyleSheet("color: #666;")

        # 左侧标题区域
        title_area = QWidget()
        title_layout = QVBoxLayout(title_area)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(5)
        title_layout.addWidget(title_label)
        title_layout.addWidget(description_label)

        # 按钮区域
        buttons_widget = QWidget()
        buttons_layout = QHBoxLayout(buttons_widget)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(10)

        # 重置按钮
        self.reset_btn = PushButton("重置")
        self.reset_btn.setIcon(FIF.UPDATE)
        self.reset_btn.setFixedSize(80, 40)

        # 保存按钮
        self.save_btn = PrimaryPushButton("保存")
        self.save_btn.setIcon(FIF.SAVE)
        self.save_btn.setFixedSize(100, 40)

        buttons_layout.addWidget(self.reset_btn)
        buttons_layout.addWidget(self.save_btn)

        # 添加到头部布局
        header_layout.addWidget(title_area)
        header_layout.addStretch()
        header_layout.addWidget(buttons_widget)

        return header_widget

    def createContentWidget(self):
        """创建内容区域"""
        # 滚动区域
        scroll_area = ScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # 去除边框
        scroll_area.setStyleSheet("""
            ScrollArea {
                border: none;
                background-color: transparent;
            }
        """)

        # 内容容器
        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setSpacing(20)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 创建配置卡片
        self.llm_config_card = LLMConfigCard()
        self.prompt_config_card = PromptConfigCard()
        self.business_hours_card = BusinessHoursCard()
        self.system_behavior_card = SystemBehaviorCard()
        self.data_management_card = DataManagementCard(
            str(data_maintenance_service.ensure_data_directory())
        )

        # 添加到布局
        content_layout.addWidget(self.llm_config_card)
        content_layout.addWidget(self.prompt_config_card)
        content_layout.addWidget(self.business_hours_card)
        content_layout.addWidget(self.system_behavior_card)
        content_layout.addWidget(self.data_management_card)
        content_layout.addStretch()

        # 设置容器样式
        content_container.setStyleSheet("""
            QWidget {
                background-color: transparent;
                border: none;
            }
        """)

        scroll_area.setWidget(content_container)

        return scroll_area

    def loadConfig(self):
        """从config模块加载配置"""
        try:
            # 从配置模块获取各个配置项
            loaded_config = {
                "llm": {
                    "provider": config.get("llm.provider", "openai_compatible"),
                    "api_base": config.get("llm.api_base", ""),
                    "api_key": config.get("llm.api_key", ""),
                    "model_name": config.get("llm.model_name", ""),
                    "endpoint_trust_mode": config.get("llm.endpoint_trust_mode", "default"),
                    "tool_policy": config.get("llm.tool_policy", "enabled"),
                    "capability_confirmation": config.get("llm.capability_confirmation", ""),
                    "tool_trust_confirmation": config.get("llm.tool_trust_confirmation", ""),
                },
                "llm_providers": config.get("llm_providers", []),
                "active_llm_provider": config.get("active_llm_provider", ""),
                "prompt": {
                    "instructions": config.get("prompt.instructions", [])
                },
                "business_hours": {
                    "start": config.get("business_hours.start", "08:00"),
                    "end": config.get("business_hours.end", "23:00")
                },
                "auto_start_reply": config.get("auto_start_reply", True),
                "launch_at_login": self._readLaunchAtLogin(),
                "system_notifications": config.get("system_notifications", True),
            }

            # 验证并设置配置
            self._validateAndSetConfig(loaded_config)
            self.logger.info("配置加载成功")

        except Exception as e:
            self.logger.error(f"加载配置失败: error_type={type(e).__name__}")
            QMessageBox.warning(self, "加载失败", f"加载配置失败：{str(e)}")
            self._loadDefaultConfig()

    def _loadDefaultConfig(self):
        """加载默认配置"""
        # 使用 config_base 作为基础配置
        default_config = copy.deepcopy(config_base)

        # 补充 UI 特定的默认值（当 config_base 中字段为空时）
        if not default_config.get("llm", {}).get("api_base"):
            default_config["llm"] = default_config.get("llm", {})
            default_config["llm"]["api_base"] = "https://ark.cn-beijing.volces.com/api/v3"
        if not default_config.get("llm", {}).get("model_name"):
            default_config["llm"]["model_name"] = "doubao-seed-1-6-flash-250828"

        self._validateAndSetConfig(default_config)
        self.logger.info("已加载默认配置")

    def _validateAndSetConfig(self, config_data):
        """验证并设置配置"""
        # 确保必要的字段存在
        validated_config = {
            "llm": config_data.get("llm", {
                "provider": "openai_compatible",
                "api_base": "",
                "api_key": "",
                "model_name": "",
                "endpoint_trust_mode": "default",
                "tool_policy": "enabled",
                "capability_confirmation": "",
                "tool_trust_confirmation": "",
            }),
            "prompt": config_data.get("prompt", {
                "instructions": []
            }),
            "business_hours": config_data.get("business_hours", {"start": "08:00", "end": "23:00"}),
            "auto_start_reply": config_data.get("auto_start_reply", True),
            "launch_at_login": config_data.get("launch_at_login", False),
            "system_notifications": config_data.get("system_notifications", True),
        }

        # 验证business_hours格式
        business_hours = validated_config["business_hours"]
        if not isinstance(business_hours, dict):
            business_hours = {"start": "08:00", "end": "23:00"}
            validated_config["business_hours"] = business_hours

        if "start" not in business_hours:
            business_hours["start"] = "08:00"
        if "end" not in business_hours:
            business_hours["end"] = "23:00"

        # 设置到界面
        self.llm_config_card.setConfig(validated_config["llm"])
        providers = config_data.get("llm_providers") or []
        active_provider_id = config_data.get("active_llm_provider", "")
        if not providers:
            providers = [{
                "id": "default",
                "name": "默认供应商",
                **validated_config["llm"],
            }]
            active_provider_id = "default"
        self.llm_config_card.setProviders(providers, active_provider_id)
        self.prompt_config_card.setConfig(validated_config["prompt"])

        # 处理业务时间配置
        business_hours_config = validated_config["business_hours"]
        self.business_hours_card.setConfig({
            "business_hours": business_hours_config,
            "auto_start_reply": validated_config["auto_start_reply"],
        })
        self.system_behavior_card.setConfig({
            "launch_at_login": validated_config["launch_at_login"],
            "system_notifications": validated_config["system_notifications"],
        })

    def _readLaunchAtLogin(self) -> bool:
        try:
            return startup_service.is_enabled()
        except Exception as exc:
            self.logger.warning(
                f"读取登录启动状态失败: error_type={type(exc).__name__}"
            )
            return config.get("launch_at_login", False)

    def openDataDirectory(self):
        path = data_maintenance_service.ensure_data_directory()
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(self, "打开失败", f"无法打开数据目录：{path}")

    def clearCacheAndLogs(self):
        reply = QMessageBox.question(
            self,
            "确认清理缓存和日志",
            "将删除运行日志和可重建的浏览器缓存。\n"
            "配置、账号登录态、知识库和聊天记录会保留。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._runMaintenance(
                "cache",
                data_maintenance_service.clear_cache_and_logs,
            )

    def clearConversationHistory(self):
        from ui.auto_reply.manager import auto_reply_manager

        if auto_reply_manager.get_running_count():
            QMessageBox.warning(
                self,
                "无法清理",
                "请先停止所有自动回复，再清空聊天记录。",
            )
            return
        reply = QMessageBox.question(
            self,
            "确认清空聊天记录",
            "将永久删除全部客户对话归档和 Agent 会话历史。\n"
            "账号、配置和知识库不会删除。此操作无法撤销，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._runMaintenance(
                "history",
                data_maintenance_service.clear_conversation_history,
            )

    def _runMaintenance(self, action: str, callback):
        if self.maintenance_worker and self.maintenance_worker.isRunning():
            return
        self.data_management_card.setActionsEnabled(False)
        worker = MaintenanceWorker(action, callback, self)
        self.maintenance_worker = worker
        worker.task_finished.connect(self._onMaintenanceFinished)
        worker.task_failed.connect(self._onMaintenanceFailed)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _onMaintenanceFinished(self, action: str, result):
        self.maintenance_worker = None
        self.data_management_card.setActionsEnabled(True)
        if action == "cache":
            freed = self._formatBytes(result.removed_bytes)
            message = (
                f"已释放 {freed}，删除 {result.removed_files} 个文件、"
                f"{result.removed_directories} 个缓存目录。"
            )
            log_view = getattr(self.window(), "log_view", None)
            if log_view is not None:
                log_view.log_display.clear_all()
        else:
            message = f"已清空 {result.removed_rows} 条聊天及 Agent 会话记录。"
            conversation_view = getattr(self.window(), "conversation_view", None)
            if conversation_view is not None:
                conversation_view.refresh(force=True)
        if result.errors:
            QMessageBox.warning(
                self,
                "部分清理未完成",
                f"{message}\n另有 {len(result.errors)} 项因文件占用或权限不足未能删除。",
            )
            return
        InfoBar.success(
            title="清理完成",
            content=message,
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self,
        )

    def _onMaintenanceFailed(self, action: str, error: str):
        self.maintenance_worker = None
        self.data_management_card.setActionsEnabled(True)
        QMessageBox.critical(self, "清理失败", error)

    @staticmethod
    def _formatBytes(size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} GB"

    def onSaveConfig(self):
        """保存配置到config模块"""
        startup_previous = None
        startup_changed = False
        try:
            # 获取各配置卡片的配置
            providers, active_provider_id, llm_config = self._validatedProviderBundle()
            prompt_config = self.prompt_config_card.getConfig()
            business_config = self.business_hours_card.getConfig()
            system_config = self.system_behavior_card.getConfig()

            # 合并配置为新的结构
            new_config = {
                "llm": llm_config,
                "llm_providers": providers,
                "active_llm_provider": active_provider_id,
                "prompt": prompt_config,
                "business_hours": business_config.get("businessHours", {"start": "08:00", "end": "23:00"}),
                "auto_start_reply": business_config.get("auto_start_reply", True),
                "launch_at_login": system_config["launch_at_login"],
                "system_notifications": system_config["system_notifications"],
                # 保持与旧配置的兼容性
                "db_path": config.get("db_path") or "./temp/channel_shop.db"
            }

            # 验证时间设置
            start_time = self.business_hours_card.start_time_picker.getTime()
            end_time = self.business_hours_card.end_time_picker.getTime()

            if start_time == end_time:
                QMessageBox.warning(self, "时间设置错误", "开始时间和结束时间不能相同！")
                return

            # 能力/端点信任三态门禁：未确认保存会作为草稿保留，不启用。
            validation = inspect_llm_draft(llm_config)
            if not self._confirm_llm_profile(
                active_provider_id, providers, llm_config, validation
            ):
                return

            startup_previous = startup_service.is_enabled()
            if startup_previous != system_config["launch_at_login"]:
                startup_service.set_enabled(system_config["launch_at_login"])
                startup_changed = True

            # 使用config模块保存配置
            config.update(new_config, save=True)
            notifier = get_system_notifier()
            if notifier is not None:
                try:
                    notifier.refresh_visibility(system_config["system_notifications"])
                except Exception as exc:
                    self.logger.warning(
                        f"刷新系统通知状态失败: error_type={type(exc).__name__}"
                    )

            self.logger.info("配置保存成功")

            # 显示成功消息
            InfoBar.success(
                title="保存成功",
                content="配置已保存！",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )

        except ValueError as e:
            if startup_changed and startup_previous is not None:
                try:
                    startup_service.set_enabled(startup_previous)
                except Exception:
                    self.logger.error("登录启动设置回滚失败")
            QMessageBox.warning(self, "配置错误", str(e))
        except Exception as e:
            if startup_changed and startup_previous is not None:
                try:
                    startup_service.set_enabled(startup_previous)
                except Exception:
                    self.logger.error("登录启动设置回滚失败")
            self.logger.error(f"保存配置失败: error_type={type(e).__name__}")
            QMessageBox.critical(self, "保存失败", f"保存配置时发生错误：{str(e)}")

    def _validatedLLMConfig(self) -> dict:
        """Validate required values and normalize the API base URL."""
        providers, active_provider_id = self.llm_config_card.getProviders()
        active_provider = next(
            (provider for provider in providers if provider.get("id") == active_provider_id),
            None,
        )
        if active_provider is None:
            raise ValueError("请选择当前使用的 LLM 供应商。")
        return self._validateActiveLLMConfig(active_provider)

    def _validatedProviderBundle(self) -> tuple[list, str, dict]:
        providers, active_provider_id = self.llm_config_card.getProviders()
        validated_providers = [
            LLMProviderConfig(**provider).model_dump() for provider in providers
        ]
        llm_config = next(
            (
                provider
                for provider in validated_providers
                if provider["id"] == active_provider_id
            ),
            None,
        )
        active_llm = self._validateActiveLLMConfig(llm_config)
        return validated_providers, active_provider_id, active_llm

    def _confirm_llm_profile(
        self,
        active_provider_id: str,
        providers: list,
        llm_config: dict,
        validation: dict,
    ) -> bool:
        if not validation["requires_confirmation"]:
            return True
        decision = validation.get("decision")
        provider_name = (
            decision.provider.value if decision else llm_config.get("provider", "")
        )
        model_name = llm_config.get("model_name", "")
        message = (
            f"{provider_name} / {model_name} 的工具调用能力或端点信任尚未验证。\n"
            "只有确认当前供应商、模型、Base URL 和工具策略后，才会启用并保存。\n"
            "取消将保留当前有效配置，编辑内容只作为未确认草稿。"
        )
        reply = QMessageBox.question(
            self,
            "确认模型能力与端点信任",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self.llm_config_card.status_label.setText("未确认：当前草稿不会启用")
            return False
        fingerprint = validation["fingerprint"]
        llm_config["capability_confirmation"] = fingerprint
        if validation["requires_tool_trust"]:
            llm_config["tool_trust_confirmation"] = fingerprint
        # 同步到 UI 内存，避免同一配置在下次保存时再次弹出确认。
        self.llm_config_card._profile_meta["capability_confirmation"] = fingerprint
        if validation["requires_tool_trust"]:
            self.llm_config_card._profile_meta["tool_trust_confirmation"] = fingerprint
        for provider in providers:
            if provider["id"] == active_provider_id:
                provider["capability_confirmation"] = fingerprint
                if validation["requires_tool_trust"]:
                    provider["tool_trust_confirmation"] = fingerprint
                break
        self.llm_config_card.status_label.setText(
            f"已验证：{llm_config.get('provider')} / {model_name}"
        )
        return True

    @staticmethod
    def _validateActiveLLMConfig(llm_config: dict) -> dict:
        if llm_config is None:
            raise ValueError("请选择当前使用的 LLM 供应商。")
        if not llm_config.get("api_key"):
            raise ValueError("请输入 LLM API Key。")
        if not llm_config.get("model_name"):
            raise ValueError("请输入 LLM 模型名称。")
        try:
            profile = build_llm_profile(
                llm_config,
                require_api_key=True,
                require_confirmation=False,
            )
        except ProfileValidationError as exc:
            raise ValueError(exc.safe_message) from exc
        return profile_to_dict(profile)

    def onTestConnection(self):
        """Run a minimal API call in a worker thread."""
        if self.connection_test_thread and self.connection_test_thread.isRunning():
            return
        try:
            llm_config = self._validatedLLMConfig()
        except Exception as exc:
            QMessageBox.warning(self, "配置错误", str(exc))
            return

        _, provider_id = self.llm_config_card.getProviders()
        self._task_provider_id = provider_id
        self.llm_config_card.setActionsEnabled(False)
        self.llm_config_card.test_btn.setText("测试中...")
        thread = LLMConnectionTestThread(llm_config, self)
        self.connection_test_thread = thread
        thread.test_finished.connect(self.onTestConnectionFinished)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def onTestConnectionFinished(self, success: bool, message: str):
        self.llm_config_card.setActionsEnabled(True)
        self.llm_config_card.test_btn.setText("测试连接")
        self.connection_test_thread = None
        if self._task_provider_id:
            self.llm_config_card.setProviderStatus(
                self._task_provider_id, success, message
            )
        self._task_provider_id = None
        if success:
            InfoBar.success(
                title="连接成功",
                content=message,
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )
        else:
            QMessageBox.warning(self, "连接失败", message)

    def onBatchTestConnections(self):
        if self.batch_test_thread and self.batch_test_thread.isRunning():
            return
        providers, _ = self.llm_config_card.getProviders()
        valid_providers = []
        initial_results = {}
        for provider in providers:
            try:
                llm_config = self._validateActiveLLMConfig(provider)
                valid_providers.append({"id": provider["id"], **llm_config})
            except Exception as exc:
                initial_results[provider["id"]] = (False, str(exc))

        self._batch_initial_results = initial_results
        if not valid_providers:
            self.onBatchTestConnectionsFinished({})
            return

        self.llm_config_card.setActionsEnabled(False)
        self.llm_config_card.batch_test_btn.setText("测试中...")
        thread = LLMBatchTestThread(valid_providers, self)
        self.batch_test_thread = thread
        thread.test_finished.connect(self.onBatchTestConnectionsFinished)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def onBatchTestConnectionsFinished(self, results: dict):
        results = {**self._batch_initial_results, **results}
        self._batch_initial_results = {}
        self.batch_test_thread = None
        self.llm_config_card.setActionsEnabled(True)
        self.llm_config_card.batch_test_btn.setText("批量测试")
        for provider_id, (success, message) in results.items():
            self.llm_config_card.setProviderStatus(provider_id, success, message)
        success_count = sum(1 for success, _ in results.values() if success)
        failure_count = len(results) - success_count
        QMessageBox.information(
            self,
            "批量测试完成",
            f"测试完成：{success_count} 个通过，{failure_count} 个失败。",
        )

    def onFetchModels(self):
        if self.model_fetch_thread and self.model_fetch_thread.isRunning():
            return
        providers, provider_id = self.llm_config_card.getProviders()
        provider = next(
            (item for item in providers if item.get("id") == provider_id), None
        )
        if provider is None:
            QMessageBox.warning(self, "配置错误", "请选择供应商。")
            return
        try:
            if not provider.get("api_key"):
                raise ValueError("请输入 LLM API Key。")
            if not provider.get("api_base"):
                raise ValueError("请输入 API Base URL。")
            llm_config = LLMConfig(**provider).model_dump()
        except Exception as exc:
            QMessageBox.warning(self, "配置错误", str(exc))
            return

        self._task_provider_id = provider_id
        self.llm_config_card.setActionsEnabled(False)
        self.llm_config_card.fetch_models_btn.setText("拉取中...")
        thread = LLMModelFetchThread(llm_config, self)
        self.model_fetch_thread = thread
        thread.fetch_finished.connect(self.onFetchModelsFinished)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def onFetchModelsFinished(self, success: bool, models: list, message: str):
        self.model_fetch_thread = None
        self.llm_config_card.setActionsEnabled(True)
        self.llm_config_card.fetch_models_btn.setText("拉取模型")
        if success:
            self.llm_config_card.setModelOptions(models)
            InfoBar.success(
                title="模型已更新",
                content=message,
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )
        else:
            QMessageBox.warning(self, "拉取失败", message)
        self._task_provider_id = None

    def onResetConfig(self):
        """重置配置"""
        reply = QMessageBox.question(
            self,
            "确认重置",
            "确定要重置所有配置吗？\n这将重新加载配置文件中的原始设置。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                # 使用config模块重新加载配置文件
                config.reload()
                self.loadConfig()
                self.logger.info("配置已重置")

                InfoBar.success(
                    title="重置成功",
                    content="配置已重置为配置文件中的设置！",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=2000,
                    parent=self
                )
            except Exception as e:
                self.logger.error(f"重置配置失败: error_type={type(e).__name__}")
                QMessageBox.critical(self, "重置失败", f"重置配置失败：{str(e)}")
