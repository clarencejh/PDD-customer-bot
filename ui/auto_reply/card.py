# 账号卡片组件模块
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QWidget, QHBoxLayout, QVBoxLayout
from PyQt6.QtGui import QFont, QPixmap
from qfluentwidgets import CardWidget, StrongBodyLabel, CaptionLabel, BodyLabel, PushButton, PrimaryPushButton, InfoBadge, FluentIcon as FIF
from ui.logo_loader import ShopLogoLoader


class AutoReplyCard(CardWidget):
    """自动回复卡片组件"""

    # 定义信号 - PyQt6 正确方式：类级别定义
    online_clicked = pyqtSignal(dict)
    offline_clicked = pyqtSignal(dict)
    auto_reply_clicked = pyqtSignal(dict)

    def __init__(self, account_data: dict, parent=None):
        super().__init__(parent)

        self.account_data = account_data
        self.shop_id = account_data.get("shop_id", "")
        self.shop_name = account_data.get("shop_name", "")
        self.shop_logo = account_data.get("shop_logo")
        self.account_name = account_data.get("username", "")
        self.account_identity = self._account_identity_text(account_data.get("is_main_account"))
        self.platform = account_data.get("channel_name", "")
        self.status = self.getStatusText(account_data.get("status", 0))
        self.auto_reply_status = False  # 自动回复状态
        self.auto_reply_pending = False  # 线程已启动但 WebSocket 尚未确认连接
        self.setupUI()
        self.connectSignals()
        self.loadLogo()

    @staticmethod
    def getStatusText(status_code: int) -> str:
        """将状态码转换为文本"""
        status_map = {
            0: "休息",
            1: "在线",
            3: "离线",
            None: "未验证"
        }
        return status_map.get(status_code, "未知")

    def setupUI(self):
        """设置卡片UI"""
        self.setFixedHeight(120)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(20)

        logo_widget = self.createLogoWidget()
        info_widget = self.createInfoWidget()
        self.action_widget = self.createActionWidget()

        layout.addWidget(logo_widget)
        layout.addWidget(info_widget, 1)
        layout.addWidget(self.action_widget, 0)

    def createLogoWidget(self):
        """创建Logo显示区域"""
        self.logo_label = QLabel()
        self.logo_label.setFixedSize(65, 65)
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_label.setStyleSheet("border-radius: 30px; border: 1px solid #e0e0e0; background-color: #f5f5f5;")
        self.logo_label.setText("加载中...")
        return self.logo_label

    def createInfoWidget(self):
        """创建信息显示区域"""
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_layout.setSpacing(8)
        info_layout.setContentsMargins(0, 0, 0, 0)

        # 第一行：店铺名称 + 平台标签
        first_row = QWidget()
        first_row_layout = QHBoxLayout(first_row)
        first_row_layout.setContentsMargins(0, 0, 0, 0)
        first_row_layout.setSpacing(10)

        shop_name_label = StrongBodyLabel(self.shop_name)
        shop_name_label.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        shop_name_label.setStyleSheet("color: #2c3e50;")

        platform_badge = InfoBadge.info(self.platform, self)
        platform_badge.setFont(QFont("Microsoft YaHei", 9))

        first_row_layout.addWidget(shop_name_label)
        first_row_layout.addWidget(platform_badge)
        first_row_layout.addStretch()

        # 第二行：店铺ID
        second_row = self.createInfoRow("店铺ID:", self.shop_id)

        # 第三行：账号名称
        third_row = self.createInfoRow("账号:", self.account_name, self.account_identity)

        info_layout.addWidget(first_row)
        info_layout.addWidget(second_row)
        info_layout.addWidget(third_row)
        info_layout.addStretch()

        return info_widget

    @staticmethod
    def _account_identity_text(is_main_account) -> str:
        if is_main_account is True:
            return "主账号"
        if is_main_account is False:
            return "子账号"
        return "身份未知"

    def createInfoRow(self, label_text: str, value_text: str, tag_text: str = ""):
        """创建信息行"""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        label = CaptionLabel(label_text)
        label.setStyleSheet("color: #7f8c8d; font-weight: 500;")
        label.setFixedWidth(60)

        value = BodyLabel(value_text)
        value.setStyleSheet("color: #34495e;")

        row_layout.addWidget(label)
        row_layout.addWidget(value)
        if tag_text:
            tag = InfoBadge.success(tag_text, self) if tag_text == "主账号" else InfoBadge.warning(tag_text, self)
            row_layout.addWidget(tag)
        row_layout.addStretch()

        return row_widget

    def createActionWidget(self):
        """创建操作区域"""
        action_widget = QWidget()
        action_layout = QVBoxLayout(action_widget)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(10)
        action_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        status_badge = self.createStatusBadge()

        buttons_widget = QWidget()
        buttons_layout = QHBoxLayout(buttons_widget)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(8)

        self.online_btn = PushButton("上线")
        self.online_btn.setIcon(FIF.PLAY)
        self.online_btn.setFixedSize(100, 32)

        self.offline_btn = PushButton("离线")
        self.offline_btn.setIcon(FIF.PAUSE)
        self.offline_btn.setFixedSize(100, 32)

        self.auto_reply_btn = PrimaryPushButton("开始回复")
        self.auto_reply_btn.setIcon(FIF.ROBOT)
        self.auto_reply_btn.setFixedSize(110, 32)

        buttons_layout.addWidget(self.online_btn)
        buttons_layout.addWidget(self.offline_btn)
        buttons_layout.addWidget(self.auto_reply_btn)

        action_layout.addWidget(status_badge, 0, Qt.AlignmentFlag.AlignRight)
        action_layout.addWidget(buttons_widget)
        action_layout.addStretch()

        return action_widget

    def createStatusBadge(self):
        """创建状态标签"""
        if self.status == "在线":
            status_badge = InfoBadge.success("● 在线", self)
        elif self.status == "离线":
            status_badge = InfoBadge.error("● 离线", self)
        elif self.status == "未验证":
            status_badge = InfoBadge.warning("● 未验证", self)
        elif self.status == "休息":
            status_badge = InfoBadge.info("● 休息", self)
        else:
            status_badge = InfoBadge.info(f"● {self.status}", self)

        status_badge.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        return status_badge

    def connectSignals(self):
        """连接信号"""
        self.online_btn.clicked.connect(lambda: self.online_clicked.emit(self.account_data))
        self.offline_btn.clicked.connect(lambda: self.offline_clicked.emit(self.account_data))
        self.auto_reply_btn.clicked.connect(lambda: self.auto_reply_clicked.emit(self.account_data))

    def setButtonsEnabled(self, enabled: bool):
        """设置按钮是否可用"""
        self.online_btn.setEnabled(enabled)
        self.offline_btn.setEnabled(enabled)

    def setButtonLoading(self, button_type: str, loading: bool):
        """设置按钮加载状态"""
        if button_type == "online":
            if loading:
                self.online_btn.setText("设置中...")
                self.online_btn.setEnabled(False)
            else:
                self.online_btn.setText("上线")
                self.online_btn.setEnabled(True)
        elif button_type == "offline":
            if loading:
                self.offline_btn.setText("设置中...")
                self.offline_btn.setEnabled(False)
            else:
                self.offline_btn.setText("离线")
                self.offline_btn.setEnabled(True)

    def setAutoReplyStatus(self, is_running: bool):
        """设置自动回复状态"""
        self.auto_reply_pending = False
        self.auto_reply_status = is_running
        if is_running:
            self.auto_reply_btn.setText("停止回复")
            self.auto_reply_btn.setIcon(FIF.CANCEL)
        else:
            self.auto_reply_btn.setText("开始回复")
            self.auto_reply_btn.setIcon(FIF.ROBOT)
        self.auto_reply_btn.setEnabled(True)

    def setAutoReplyConnecting(self, connecting: bool):
        """显示等待 WebSocket 连接结果的状态。"""
        self.auto_reply_pending = connecting
        if connecting:
            self.auto_reply_btn.setText("连接中...")
            self.auto_reply_btn.setEnabled(False)
        else:
            self.auto_reply_btn.setEnabled(True)

    def updateStatus(self, new_status: int):
        """更新账号状态"""
        self.account_data["status"] = new_status
        self.status = self.getStatusText(new_status)

        old_badge = self.action_widget.layout().itemAt(0).widget()
        if old_badge:
            old_badge.deleteLater()

        new_badge = self.createStatusBadge()
        self.action_widget.layout().insertWidget(0, new_badge, 0, Qt.AlignmentFlag.AlignRight)

    def loadLogo(self):
        """异步加载Logo"""
        if self.shop_logo:
            self.logo_loader = ShopLogoLoader(self.shop_logo, self)
            self.logo_loader.logo_loaded.connect(self.setLogo)
            self.logo_loader.start()
        else:
            self.logo_label.setText("无Logo")

    def setLogo(self, pixmap: QPixmap):
        """设置Logo"""
        if not pixmap.isNull():
            self.logo_label.setPixmap(pixmap)
        else:
            self.logo_label.setText("加载失败")


__all__ = ['AutoReplyCard']
