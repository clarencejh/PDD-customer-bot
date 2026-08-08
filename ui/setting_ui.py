# 设置界面

import json
import os
import asyncio
import copy
import uuid
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QVBoxLayout, QWidget, QLabel,
                            QFormLayout, QGroupBox, QMessageBox, QDialog,
                            QListWidgetItem)
from PyQt6.QtGui import QFont
from qfluentwidgets import (CardWidget, SubtitleLabel, CaptionLabel, BodyLabel,
                           PrimaryPushButton, PushButton, StrongBodyLabel,
                           LineEdit, ComboBox, ScrollArea, FluentIcon as FIF,
                           InfoBar, InfoBarPosition, TextEdit, PasswordLineEdit,
                           TimePicker, ListWidget, EditableComboBox, SwitchButton)
from PyQt6.QtCore import QTime
from utils.logger_loguru import get_logger
from config import LLMConfig, LLMProviderConfig, config, config_base
from Agent.CustomerAgent.custom.llm_client import LLMClient
from service.llm_service import llm_error_message
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
        client = LLMClient(
            api_key=self.llm_config["api_key"],
            api_base=self.llm_config["api_base"],
            model_name=self.llm_config["model_name"],
            temperature=0,
        )
        try:
            await client.initialize()
            await client.test_connection()
        finally:
            await client.close()


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
                client = LLMClient(
                    api_key=provider["api_key"],
                    api_base=provider["api_base"],
                    model_name=provider["model_name"],
                    temperature=0,
                )
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
        client = LLMClient(
            api_key=self.llm_config["api_key"],
            api_base=self.llm_config["api_base"],
            model_name=self.llm_config.get("model_name", ""),
            temperature=0,
        )
        try:
            await client.initialize()
            return await client.list_models()
        finally:
            await client.close()


class AddLLMProviderDialog(QDialog):
    """Dialog for creating a provider record."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加供应商")
        self.setModal(True)
        self.resize(520, 280)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(12)
        self.name_edit = LineEdit()
        self.name_edit.setPlaceholderText("供应商名称")
        self.api_base_edit = LineEdit()
        self.api_base_edit.setPlaceholderText("https://api.example.com/v1")
        self.api_key_edit = PasswordLineEdit()
        self.api_key_edit.setPlaceholderText("API Key")
        self.model_edit = LineEdit()
        self.model_edit.setPlaceholderText("可稍后拉取或手动输入")
        form.addRow("供应商名称:", self.name_edit)
        form.addRow("API Base URL:", self.api_base_edit)
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
            "api_base": self.api_base_edit.text().strip(),
            "api_key": self.api_key_edit.text().strip(),
            "model_name": self.model_edit.text().strip(),
        }




class LLMConfigCard(CardWidget):
    """LLM配置卡片"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.providers = []
        self.provider_status = {}
        self._current_provider_id = None
        self._loading_provider = False
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

        # API Base URL
        self.api_base_edit = LineEdit()
        self.api_base_edit.setPlaceholderText("https://ark.cn-beijing.volces.com/api/v3")
        self.api_base_edit.setText("https://ark.cn-beijing.volces.com/api/v3")
        form_layout.addRow("API Base URL:", self.api_base_edit)

        # API Key
        self.api_key_edit = PasswordLineEdit()
        self.api_key_edit.setPlaceholderText("输入您的 API Key")
        form_layout.addRow("API Key:", self.api_key_edit)

        # Model Name
        self.model_name_edit = EditableComboBox()
        self.model_name_edit.setPlaceholderText("输入模型名称，如：doubao-seed-1-6-flash-250828")
        form_layout.addRow("模型名称:", self.model_name_edit)

        detail_layout.addLayout(form_layout)

        # 说明文本
        description_label = CaptionLabel(
            "配置LLM模型的连接参数。\n"
            "支持OpenAI兼容的API接口，包括豆包、通义千问等模型。"
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
        """获取配置"""
        self._storeCurrentProvider()
        return {
            "api_base": self.api_base_edit.text().strip() or "https://ark.cn-beijing.volces.com/api/v3",
            "api_key": self.api_key_edit.text().strip(),
            "model_name": self.model_name_edit.currentText().strip()
        }

    def setConfig(self, config: dict):
        """设置配置"""
        self.api_base_edit.setText(config.get("api_base", "https://ark.cn-beijing.volces.com/api/v3"))
        self.api_key_edit.setText(config.get("api_key", ""))
        self.model_name_edit.clear()
        model_name = config.get("model_name", "")
        if model_name:
            self.model_name_edit.addItem(model_name)
        self.model_name_edit.setCurrentText(model_name)

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
        provider.update({
            "name": self.provider_name_edit.text().strip() or provider.get("name", "供应商"),
            "api_base": self.api_base_edit.text().strip(),
            "api_key": self.api_key_edit.text().strip(),
            "model_name": self.model_name_edit.currentText().strip(),
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


class SettingUI(QFrame):
    """设置界面"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.logger = get_logger("SettingUI")
        self.connection_test_thread = None
        self.batch_test_thread = None
        self.model_fetch_thread = None
        self._task_provider_id = None
        self._batch_initial_results = {}
        self.setupUI()
        self.loadConfig()

        # 设置对象名
        self.setObjectName("设置")

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

        # 添加到布局
        content_layout.addWidget(self.llm_config_card)
        content_layout.addWidget(self.prompt_config_card)
        content_layout.addWidget(self.business_hours_card)
        content_layout.addWidget(self.system_behavior_card)
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
                    "api_base": config.get("llm.api_base", "https://ark.cn-beijing.volces.com/api/v3"),
                    "api_key": config.get("llm.api_key", ""),
                    "model_name": config.get("llm.model_name", "doubao-seed-1-6-flash-250828")
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
                "api_base": "https://ark.cn-beijing.volces.com/api/v3",
                "api_key": "",
                "model_name": "doubao-seed-1-6-flash-250828"
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

    @staticmethod
    def _validateActiveLLMConfig(llm_config: dict) -> dict:
        if llm_config is None:
            raise ValueError("请选择当前使用的 LLM 供应商。")
        if not llm_config.get("api_key"):
            raise ValueError("请输入 LLM API Key。")
        if not llm_config.get("model_name"):
            raise ValueError("请输入 LLM 模型名称。")
        if not llm_config.get("api_base"):
            raise ValueError("请输入 API Base URL。")
        return LLMConfig(**llm_config).model_dump()

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
