"""项目关于页面。"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FluentIcon as FIF,
    HyperlinkButton,
    IconWidget,
    ScrollArea,
    StrongBodyLabel,
    TitleLabel,
)

from utils.runtime_path import get_resource_path


PROJECT_URL = "https://github.com/JC0v0/Customer-Agent"


class AboutUI(QFrame):
    """展示项目信息、主要能力与联系渠道。"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("aboutInterface")
        self._setup_ui()

    def _setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = ScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll_area.setStyleSheet("ScrollArea { border: none; background: transparent; }")

        canvas = QWidget()
        canvas.setObjectName("aboutCanvas")
        canvas.setStyleSheet("#aboutCanvas { background: transparent; }")
        canvas_layout = QHBoxLayout(canvas)
        canvas_layout.setContentsMargins(32, 32, 32, 40)

        page = QWidget()
        page.setMaximumWidth(960)
        page.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(20)

        page_layout.addWidget(self._create_header())
        page_layout.addWidget(self._create_project_card())
        page_layout.addWidget(self._create_contact_card())
        page_layout.addStretch()

        canvas_layout.addStretch()
        canvas_layout.addWidget(page, 1)
        canvas_layout.addStretch()
        scroll_area.setWidget(canvas)
        root_layout.addWidget(scroll_area)

    def _create_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(4, 4, 4, 8)
        layout.setSpacing(18)

        app_icon = QLabel()
        app_icon.setFixedSize(72, 72)
        pixmap = QIcon(str(get_resource_path("icon/icon.ico"))).pixmap(64, 64)
        app_icon.setPixmap(pixmap)
        app_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(5)
        title = TitleLabel("Agent-Customer")
        subtitle = BodyLabel("面向电商场景的 AI 客服桌面应用")
        subtitle.setWordWrap(True)
        meta = CaptionLabel("Python 3.11+  ·  PyQt6  ·  OpenAI 兼容 API  ·  MIT License")
        meta.setWordWrap(True)
        text_layout.addWidget(title)
        text_layout.addWidget(subtitle)
        text_layout.addWidget(meta)

        layout.addWidget(app_icon, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(text_layout, 1)
        return header

    def _create_project_card(self) -> CardWidget:
        card = CardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(16)

        title = StrongBodyLabel("关于项目")
        description = BodyLabel(
            "Agent-Customer 为电商客服团队提供自动回复、知识检索、商品推荐、"
            "消息处理和人工接管能力。目前重点支持拼多多渠道，并通过模块化渠道层"
            "为后续平台扩展保留清晰边界。"
        )
        description.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(description)

        features = QGridLayout()
        features.setHorizontalSpacing(28)
        features.setVerticalSpacing(18)
        feature_items = [
            (FIF.CHAT, "智能回复", "多轮对话、工具调用与上下文管理"),
            (FIF.DOCUMENT, "双知识库", "产品知识与客服政策分别检索"),
            (FIF.SYNC, "实时连接", "消息队列、自动重连与账号状态隔离"),
            (FIF.SHOPPING_CART, "商品协同", "同步商品信息并发送商品卡片"),
        ]
        for index, (icon, name, detail) in enumerate(feature_items):
            features.addWidget(
                self._create_feature(icon, name, detail), index // 2, index % 2
            )
        layout.addLayout(features)

        project_link = HyperlinkButton()
        project_link.setIcon(FIF.GITHUB)
        project_link.setText("访问 GitHub 项目")
        project_link.setUrl(PROJECT_URL)
        project_link.setFixedHeight(36)
        layout.addWidget(project_link, 0, Qt.AlignmentFlag.AlignLeft)
        return card

    @staticmethod
    def _create_feature(icon, name: str, detail: str) -> QWidget:
        item = QWidget()
        layout = QHBoxLayout(item)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        icon_widget = IconWidget()
        icon_widget.setIcon(icon)
        icon_widget.setFixedSize(24, 24)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)
        name_label = StrongBodyLabel(name)
        detail_label = CaptionLabel(detail)
        detail_label.setWordWrap(True)
        text_layout.addWidget(name_label)
        text_layout.addWidget(detail_label)

        layout.addWidget(icon_widget, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(text_layout, 1)
        return item

    def _create_contact_card(self) -> CardWidget:
        card = CardWidget()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(32)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 4, 0, 4)
        text_layout.setSpacing(10)
        title = StrongBodyLabel("联系我们")
        description = BodyLabel(
            "扫描右侧二维码，获取项目动态、使用支持与问题反馈渠道。"
        )
        description.setWordWrap(True)
        note = CaptionLabel("反馈问题时，请附上应用日志、系统版本和复现步骤。")
        note.setWordWrap(True)
        text_layout.addWidget(title)
        text_layout.addWidget(description)
        text_layout.addWidget(note)
        text_layout.addStretch()

        qr_label = QLabel()
        qr_label.setFixedSize(220, 220)
        qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_label.setToolTip("联系二维码")
        qr = QIcon(str(get_resource_path("icon/Customer-Agent-qr.png"))).pixmap(204, 204)
        qr_label.setPixmap(qr)

        layout.addLayout(text_layout, 1)
        layout.addWidget(qr_label, 0, Qt.AlignmentFlag.AlignCenter)
        return card
