"""Conversation archive browser with a customer-grouped chat layout."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    TextEdit,
    isDarkTheme,
)

from database.conversation_archive import ConversationArchiveService
from database.db_manager import get_db_manager


SENDER_LABELS = {
    "user": "客户",
    "ai": "AI 客服",
    "human": "人工客服",
    "system": "系统",
}
MESSAGE_TYPE_LABELS = {
    "text": "文本",
    "image": "图片",
    "video": "视频",
    "emotion": "表情",
    "goods_card": "商品卡片",
    "goods_inquiry": "商品咨询",
    "goods_spec": "商品规格",
    "order_info": "订单信息",
}
EVENT_LABELS = {
    "transfer": "会话发生转接",
    "transfer_to_human": "会话已转人工客服",
    "transfer_to_ai": "会话已转回 AI 客服",
    "account_authenticated": "客服账号连接成功",
    "customer_session_ready": "客户会话已建立",
    "message_withdrawn": "消息已撤回",
    "system_status": "系统状态已更新",
    "system_notice": "系统通知",
}


def _identity_label(name: Any, identity: Any) -> str:
    name_text = str(name or "").strip()
    identity_text = str(identity or "").strip()
    if name_text and identity_text and name_text != identity_text:
        return f"{name_text} ({identity_text})"
    return name_text or identity_text


def _parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _list_time(value: Any) -> str:
    parsed = _parse_time(value)
    if not parsed:
        return ""
    today = datetime.now().date()
    if parsed.date() == today:
        return parsed.strftime("%H:%M")
    if parsed.year == today.year:
        return parsed.strftime("%m-%d")
    return parsed.strftime("%Y-%m-%d")


def _message_time(value: Any) -> str:
    parsed = _parse_time(value)
    return parsed.strftime("%H:%M") if parsed else ""


def _message_date(value: Any) -> str:
    parsed = _parse_time(value)
    return parsed.strftime("%Y年%m月%d日") if parsed else ""


def _preview(record: Dict[str, Any]) -> str:
    event_type = record.get("event_type")
    if event_type and event_type != "message":
        return EVENT_LABELS.get(event_type, str(record.get("content") or "会话事件"))
    sender = SENDER_LABELS.get(record.get("sender_type"), "")
    content = " ".join(str(record.get("content") or "").split())
    if not content:
        content = MESSAGE_TYPE_LABELS.get(record.get("message_type"), "消息")
    prefix = f"{sender}: " if sender else ""
    text = f"{prefix}{content}"
    return text if len(text) <= 42 else f"{text[:42]}..."


def _thread_key(record: Dict[str, Any]) -> str:
    return "|".join(
        str(record.get(key) or "")
        for key in ("channel_name", "shop_id", "customer_uid")
    )


def _available_cs_options(
    cs_list: Any, shop_id: Any, account_user_id: Any
) -> List[Tuple[str, str]]:
    """Normalize platform customer-service data for the transfer picker."""
    if not isinstance(cs_list, dict):
        return []
    own_cs_uid = f"cs_{shop_id}_{account_user_id}"
    options = []
    for cs_uid, details in cs_list.items():
        uid = str(cs_uid or "").strip()
        if not uid or uid == own_cs_uid:
            continue
        username = details.get("username") if isinstance(details, dict) else None
        options.append((_identity_label(username, uid), uid))
    return sorted(options, key=lambda item: item[0].lower())


def _theme_colors() -> Dict[str, str]:
    if isDarkTheme():
        return {
            "root": "#191c21",
            "text": "#f1f3f5",
            "muted": "#a9b0b8",
            "border": "#343941",
            "panel": "#202329",
            "neutral": "#2b3037",
            "outbound": "#244f75",
            "event": "#30353d",
            "selected": "rgba(64, 145, 221, 0.22)",
        }
    return {
        "root": "#f4f5f7",
        "text": "#202124",
        "muted": "#69717c",
        "border": "#e3e6ea",
        "panel": "#f7f8fa",
        "neutral": "#f0f2f5",
        "outbound": "#d9ecff",
        "event": "#eef0f3",
        "selected": "rgba(0, 120, 212, 0.12)",
    }


class ConversationListRow(QWidget):
    """Compact summary shown in the customer conversation list."""

    def __init__(self, conversation: Dict[str, Any], parent=None):
        super().__init__(parent)
        colors = _theme_colors()
        customer_name = conversation.get("customer_nickname") or conversation.get(
            "customer_uid"
        ) or "未知客户"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(10)

        avatar = QLabel(str(customer_name)[:1].upper())
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFixedSize(42, 42)
        avatar.setStyleSheet(
            "QLabel { background: #3b82b6; color: white; border-radius: 6px; "
            "font-size: 16px; font-weight: 600; }"
        )
        layout.addWidget(avatar)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(3)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        name = StrongBodyLabel(str(customer_name))
        name.setStyleSheet(f"color: {colors['text']};")
        timestamp = CaptionLabel(_list_time(conversation.get("created_at")))
        timestamp.setStyleSheet(f"color: {colors['muted']};")
        top.addWidget(name, 1)
        top.addWidget(timestamp)
        text_column.addLayout(top)

        preview = CaptionLabel(_preview(conversation))
        preview.setStyleSheet(f"color: {colors['muted']};")
        text_column.addWidget(preview)

        scope = CaptionLabel(
            _identity_label(conversation.get("shop_name"), conversation.get("shop_id"))
        )
        scope.setStyleSheet(f"color: {colors['muted']}; font-size: 11px;")
        text_column.addWidget(scope)
        layout.addLayout(text_column, 1)


class MessageBubble(QWidget):
    """One chat message aligned by direction."""

    def __init__(self, record: Dict[str, Any], parent=None):
        super().__init__(parent)
        colors = _theme_colors()
        outbound = record.get("direction") == "outbound"

        row = QHBoxLayout(self)
        row.setContentsMargins(18, 4, 18, 4)
        row.setSpacing(12)
        if outbound:
            row.addStretch(1)

        bubble = QFrame()
        bubble.setObjectName("messageBubble")
        bubble.setMaximumWidth(760)
        bubble.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        background = colors["outbound"] if outbound else colors["neutral"]
        bubble.setStyleSheet(
            f"QFrame#messageBubble {{ background: {background}; border-radius: 6px; }}"
        )
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 8, 12, 9)
        bubble_layout.setSpacing(4)

        sender = SENDER_LABELS.get(record.get("sender_type"), "消息")
        message_type = MESSAGE_TYPE_LABELS.get(record.get("message_type"), "")
        meta_text = sender
        account_name = str(record.get("account_username") or "").strip()
        if account_name and record.get("sender_type") in {"ai", "human"}:
            meta_text = f"{meta_text}  {account_name}"
        if message_type and record.get("message_type") != "text":
            meta_text = f"{meta_text}  {message_type}"
        meta = CaptionLabel(meta_text)
        meta.setStyleSheet(
            f"color: {colors['muted']}; font-size: 11px; background: transparent;"
        )
        bubble_layout.addWidget(meta)

        content_text = str(record.get("content") or "")
        if not content_text:
            content_text = f"[{message_type or '消息'}]"
        content = BodyLabel(content_text)
        content.setWordWrap(True)
        content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content.setStyleSheet(f"color: {colors['text']}; background: transparent;")
        bubble_layout.addWidget(content)

        longest_line = max(content_text.splitlines() or [content_text], key=len)
        measured_width = content.fontMetrics().horizontalAdvance(longest_line)
        bubble.setMinimumWidth(max(150, min(760, measured_width + 42)))

        time_label = CaptionLabel(_message_time(record.get("created_at")))
        time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        time_label.setStyleSheet(
            f"color: {colors['muted']}; font-size: 10px; background: transparent;"
        )
        bubble_layout.addWidget(time_label)
        row.addWidget(bubble)

        if not outbound:
            row.addStretch(1)


class ConversationEvent(QWidget):
    def __init__(self, record: Dict[str, Any], parent=None):
        super().__init__(parent)
        colors = _theme_colors()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 7, 18, 7)
        layout.addStretch(1)
        text = EVENT_LABELS.get(
            record.get("event_type"), str(record.get("content") or "会话事件")
        )
        timestamp = _message_time(record.get("created_at"))
        label = CaptionLabel(f"{text}  {timestamp}".strip())
        label.setStyleSheet(
            f"color: {colors['muted']}; background: transparent; padding: 5px 10px;"
        )
        layout.addWidget(label)
        layout.addStretch(1)


class ReplyTextEdit(TextEdit):
    send_requested = pyqtSignal()

    def keyPressEvent(self, event):
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.send_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class ConversationActionThread(QThread):
    action_done = pyqtSignal(str, object, str)

    def __init__(self, action: str, callback: Callable[[], Any], parent=None):
        super().__init__(parent)
        self.action = action
        self.callback = callback

    def run(self):
        try:
            self.action_done.emit(self.action, self.callback(), "")
        except Exception as exc:
            self.action_done.emit(self.action, None, type(exc).__name__)


class ConversationUI(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("conversationArchive")
        self.archive = ConversationArchiveService()
        self._accounts = []
        self._conversations: Dict[str, Dict[str, Any]] = {}
        self._conversation_signature = None
        self._active_conversation: Optional[Dict[str, Any]] = None
        self._action_workers = set()
        self._action_in_progress = False
        self._pending_reply_text = ""
        self._pending_transfer_label = ""
        self._ready = False
        self._setup_ui()
        self._load_accounts()
        self._ready = True
        self.refresh(force=True)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(1500)
        self.refresh_timer.timeout.connect(self._refresh_if_visible)
        self.refresh_timer.start()

    def _setup_ui(self):
        colors = _theme_colors()
        self.setStyleSheet(
            f"QFrame#conversationArchive {{ background: {colors['root']}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 20, 26, 22)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        title_column.addWidget(SubtitleLabel("对话记录"))
        self.summary_label = CaptionLabel("按客户查看历史会话")
        self.summary_label.setStyleSheet(f"color: {colors['muted']};")
        title_column.addWidget(self.summary_label)
        header.addLayout(title_column)
        header.addStretch(1)

        self.shop_combo = ComboBox()
        self.shop_combo.setMinimumWidth(170)
        self.account_combo = ComboBox()
        self.account_combo.setMinimumWidth(160)
        self.customer_input = LineEdit()
        self.customer_input.setPlaceholderText("搜索客户昵称或 UID")
        self.customer_input.setClearButtonEnabled(True)
        self.customer_input.setMinimumWidth(210)
        refresh_button = PrimaryPushButton("刷新", self, FIF.SYNC)
        header.addWidget(self.shop_combo)
        header.addWidget(self.account_combo)
        header.addWidget(self.customer_input)
        header.addWidget(refresh_button)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet(f"QSplitter::handle {{ background: {colors['border']}; }}")

        left_panel = QFrame()
        left_panel.setObjectName("conversationListPanel")
        left_panel.setMinimumWidth(270)
        left_panel.setMaximumWidth(360)
        left_panel.setStyleSheet(
            f"QFrame#conversationListPanel {{ background: {colors['panel']}; "
            f"border: 1px solid {colors['border']}; border-radius: 6px; }}"
        )
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(4)
        self.list_empty_label = BodyLabel("暂无符合条件的会话")
        self.list_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.list_empty_label.setStyleSheet(f"color: {colors['muted']}; padding: 28px;")
        self.conversation_list = QListWidget()
        self.conversation_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.conversation_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.conversation_list.setStyleSheet(
            "QListWidget { border: none; background: transparent; outline: none; }"
            "QListWidget::item { border-radius: 6px; margin: 1px 0; }"
            f"QListWidget::item:selected {{ background: {colors['selected']}; }}"
        )
        left_layout.addWidget(self.list_empty_label)
        left_layout.addWidget(self.conversation_list, 1)
        splitter.addWidget(left_panel)

        self.detail_stack = QStackedWidget()
        self.detail_stack.setObjectName("conversationDetail")
        self.detail_stack.setStyleSheet(
            f"QStackedWidget#conversationDetail {{ border: 1px solid {colors['border']}; "
            f"border-radius: 6px; background: {colors['panel']}; }}"
        )
        empty_detail = QWidget()
        empty_detail.setStyleSheet(f"background: {colors['panel']};")
        empty_layout = QVBoxLayout(empty_detail)
        empty_layout.addStretch(1)
        empty_title = StrongBodyLabel("选择一个客户查看对话")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_description = CaptionLabel("消息将按照发送时间排列")
        empty_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_description.setStyleSheet(f"color: {colors['muted']};")
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_description)
        empty_layout.addStretch(1)
        self.detail_stack.addWidget(empty_detail)

        chat_page = QWidget()
        chat_page.setStyleSheet(f"background: {colors['panel']};")
        chat_layout = QVBoxLayout(chat_page)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)
        chat_header = QFrame()
        chat_header.setObjectName("chatHeader")
        chat_header.setStyleSheet(
            f"QFrame#chatHeader {{ border: none; border-bottom: 1px solid {colors['border']}; }}"
        )
        chat_header_layout = QVBoxLayout(chat_header)
        chat_header_layout.setContentsMargins(18, 12, 18, 11)
        chat_header_layout.setSpacing(2)
        self.chat_title = StrongBodyLabel("")
        self.chat_scope = CaptionLabel("")
        self.chat_scope.setStyleSheet(f"color: {colors['muted']};")
        chat_header_layout.addWidget(self.chat_title)
        chat_header_layout.addWidget(self.chat_scope)
        chat_layout.addWidget(chat_header)

        self.messages_scroll = QScrollArea()
        self.messages_scroll.setWidgetResizable(True)
        self.messages_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.messages_scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {colors['panel']}; }} "
            f"QScrollArea > QWidget > QWidget {{ background: {colors['panel']}; }}"
        )
        self.messages_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.messages_canvas = QWidget()
        self.messages_canvas.setStyleSheet(f"background: {colors['panel']};")
        self.messages_layout = QVBoxLayout(self.messages_canvas)
        self.messages_layout.setContentsMargins(0, 12, 0, 12)
        self.messages_layout.setSpacing(1)
        self.messages_scroll.setWidget(self.messages_canvas)
        chat_layout.addWidget(self.messages_scroll, 1)

        composer = QFrame()
        composer.setObjectName("conversationComposer")
        composer.setStyleSheet(
            f"QFrame#conversationComposer {{ border: none; "
            f"border-top: 1px solid {colors['border']}; background: {colors['panel']}; }}"
        )
        composer_layout = QHBoxLayout(composer)
        composer_layout.setContentsMargins(14, 12, 14, 12)
        composer_layout.setSpacing(10)
        self.reply_input = ReplyTextEdit()
        self.reply_input.setPlaceholderText("输入回复内容")
        self.reply_input.setMinimumHeight(72)
        self.reply_input.setMaximumHeight(110)
        composer_layout.addWidget(self.reply_input, 1)

        action_column = QVBoxLayout()
        action_column.setContentsMargins(0, 0, 0, 0)
        action_column.setSpacing(8)
        self.transfer_button = PushButton("转人工", self, FIF.PEOPLE)
        self.send_button = PrimaryPushButton("发送", self, FIF.SEND)
        self.transfer_button.setFixedSize(104, 34)
        self.send_button.setFixedSize(104, 34)
        action_column.addWidget(self.transfer_button)
        action_column.addWidget(self.send_button)
        action_column.addStretch(1)
        composer_layout.addLayout(action_column)
        chat_layout.addWidget(composer)

        self.detail_stack.addWidget(chat_page)
        splitter.addWidget(self.detail_stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([305, 995])
        layout.addWidget(splitter, 1)

        self.shop_combo.currentIndexChanged.connect(self._on_shop_changed)
        self.account_combo.currentIndexChanged.connect(self._filters_changed)
        self.customer_input.returnPressed.connect(self.refresh)
        refresh_button.clicked.connect(lambda: self.refresh(force=True))
        self.conversation_list.currentItemChanged.connect(
            self._on_conversation_selected
        )
        self.reply_input.send_requested.connect(self._send_reply)
        self.send_button.clicked.connect(self._send_reply)
        self.transfer_button.clicked.connect(self._choose_transfer_target)
        self._set_composer_enabled(False)

    def _load_accounts(self):
        self._accounts = get_db_manager().get_all_accounts_with_details()
        self.shop_combo.blockSignals(True)
        self.shop_combo.clear()
        self.shop_combo.addItem("全部店铺", userData=None)
        seen = set()
        for account in self._accounts:
            shop_id = str(account.get("shop_id") or "")
            if not shop_id or shop_id in seen:
                continue
            seen.add(shop_id)
            self.shop_combo.addItem(
                _identity_label(account.get("shop_name"), shop_id), userData=shop_id
            )
        self.shop_combo.blockSignals(False)
        self._populate_accounts()

    def _populate_accounts(self):
        shop_id = self.shop_combo.currentData()
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        self.account_combo.addItem("全部客服账号", userData=None)
        for account in self._accounts:
            if shop_id and str(account.get("shop_id")) != str(shop_id):
                continue
            user_id = str(account.get("user_id") or "")
            self.account_combo.addItem(
                _identity_label(account.get("username"), user_id), userData=user_id
            )
        self.account_combo.blockSignals(False)

    def _on_shop_changed(self):
        self._populate_accounts()
        if self._ready:
            self.refresh(force=True)

    def _filters_changed(self):
        if self._ready:
            self.refresh(force=True)

    def _refresh_if_visible(self):
        if self.isVisible():
            self.refresh()

    def refresh(self, force=False):
        self.archive.reconcile_system_records()
        selected_id = None
        current = self.conversation_list.currentItem()
        if current:
            selected_id = current.data(Qt.ItemDataRole.UserRole)

        conversations = self.archive.list_conversations(
            shop_id=self.shop_combo.currentData(),
            account_user_id=self.account_combo.currentData(),
            search=self.customer_input.text().strip() or None,
            limit=300,
        )
        signature = tuple(
            (
                _thread_key(item),
                item.get("created_at"),
                item.get("message_count"),
                item.get("content"),
                item.get("event_type"),
            )
            for item in conversations
        )
        if not force and signature == self._conversation_signature:
            return
        self._conversation_signature = signature
        self._conversations = {
            _thread_key(item): item for item in conversations
        }
        self.conversation_list.clear()
        selected_row = -1
        for row, conversation in enumerate(conversations):
            thread_key = _thread_key(conversation)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, thread_key)
            item.setSizeHint(QSize(0, 82))
            self.conversation_list.addItem(item)
            self.conversation_list.setItemWidget(
                item, ConversationListRow(conversation, self.conversation_list)
            )
            if thread_key == selected_id:
                selected_row = row

        has_conversations = bool(conversations)
        self.list_empty_label.setVisible(not has_conversations)
        self.conversation_list.setVisible(has_conversations)
        self.summary_label.setText(f"共 {len(conversations)} 个客户会话")
        if has_conversations:
            self.conversation_list.setCurrentRow(
                selected_row if selected_row >= 0 else 0
            )
        else:
            self.detail_stack.setCurrentIndex(0)

    def _on_conversation_selected(self, current, _previous):
        if current is None:
            self._active_conversation = None
            self._set_composer_enabled(False)
            self.detail_stack.setCurrentIndex(0)
            return
        thread_key = str(current.data(Qt.ItemDataRole.UserRole))
        conversation = self._conversations.get(thread_key)
        if not conversation:
            self._active_conversation = None
            self._set_composer_enabled(False)
            self.detail_stack.setCurrentIndex(0)
            return
        self._active_conversation = conversation
        self._set_composer_enabled(True)
        records = self.archive.list_records(
            channel_name=conversation.get("channel_name"),
            shop_id=conversation.get("shop_id"),
            customer_uid=conversation.get("customer_uid"),
            limit=2000,
            ascending=True,
        )
        self._render_conversation(conversation, records)

    def _render_conversation(self, conversation, records):
        customer = _identity_label(
            conversation.get("customer_nickname"), conversation.get("customer_uid")
        ) or "未知客户"
        shop = _identity_label(
            conversation.get("shop_name"), conversation.get("shop_id")
        )
        account = _identity_label(
            conversation.get("account_username"),
            conversation.get("account_user_id"),
        )
        self.chat_title.setText(customer)
        self.chat_scope.setText(
            f"{shop}  |  最近客服账号 {account}  |  共 {len(records)} 条记录"
        )

        while self.messages_layout.count():
            item = self.messages_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.messages_layout.addStretch(1)

        if not records:
            empty = BodyLabel("暂无消息记录")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {_theme_colors()['muted']}; padding: 24px;")
            self.messages_layout.addWidget(empty)

        current_date = None
        for record in records:
            record_date = _message_date(record.get("created_at"))
            if record_date and record_date != current_date:
                current_date = record_date
                date_label = CaptionLabel(record_date)
                date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                date_label.setStyleSheet(
                    f"color: {_theme_colors()['muted']}; padding: 8px 0 4px; "
                    "background: transparent;"
                )
                self.messages_layout.addWidget(date_label)
            if record.get("direction") == "event":
                widget = ConversationEvent(record, self.messages_canvas)
            else:
                widget = MessageBubble(record, self.messages_canvas)
            self.messages_layout.addWidget(widget)

        self.detail_stack.setCurrentIndex(1)
        QTimer.singleShot(
            0,
            lambda: self.messages_scroll.verticalScrollBar().setValue(
                self.messages_scroll.verticalScrollBar().maximum()
            ),
        )

    def _set_composer_enabled(self, enabled: bool):
        controls_enabled = enabled and not self._action_in_progress
        self.reply_input.setEnabled(controls_enabled)
        self.send_button.setEnabled(controls_enabled)
        self.transfer_button.setEnabled(controls_enabled)

    def _show_notice(self, level: str, content: str):
        getattr(InfoBar, level)(
            title="",
            content=content,
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2500,
            parent=self,
        )

    def _start_action(self, action: str, callback: Callable[[], Any]):
        if self._action_in_progress:
            return
        self._action_in_progress = True
        self._set_composer_enabled(bool(self._active_conversation))
        worker = ConversationActionThread(action, callback, self)
        self._action_workers.add(worker)
        worker.action_done.connect(self._on_action_done)
        worker.finished.connect(lambda worker=worker: self._release_worker(worker))
        worker.start()

    def _release_worker(self, worker: ConversationActionThread):
        self._action_workers.discard(worker)
        worker.deleteLater()

    def _conversation_action_scope(self) -> Optional[Tuple[Any, Any, Any, Any]]:
        conversation = self._active_conversation
        if not conversation:
            return None
        return (
            conversation.get("channel_name"),
            conversation.get("shop_id"),
            conversation.get("account_user_id"),
            conversation.get("customer_uid"),
        )

    def _send_reply(self):
        content = self.reply_input.toPlainText().strip()
        scope = self._conversation_action_scope()
        if not content or not scope or self._action_in_progress:
            return
        channel_name, shop_id, account_user_id, customer_uid = scope
        from bridge.sender import get_sender

        sender = get_sender(channel_name)
        if not sender:
            self._show_notice("warning", "当前渠道不支持人工回复")
            return
        self._pending_reply_text = content
        self._start_action(
            "send",
            lambda: sender.send_text(
                shop_id, account_user_id, customer_uid, content, "human"
            ),
        )

    def _choose_transfer_target(self):
        scope = self._conversation_action_scope()
        if not scope or self._action_in_progress:
            return
        channel_name, shop_id, account_user_id, _customer_uid = scope
        from bridge.sender import get_sender

        sender = get_sender(channel_name)
        if not sender:
            self._show_notice("warning", "当前渠道不支持会话转移")
            return
        self._start_action(
            "load_cs", lambda: sender.get_cs_list(shop_id, account_user_id)
        )

    def _start_transfer(self, cs_uid: str, label: str):
        scope = self._conversation_action_scope()
        if not scope:
            return
        channel_name, shop_id, account_user_id, customer_uid = scope
        from bridge.sender import get_sender

        sender = get_sender(channel_name)
        if not sender:
            self._show_notice("warning", "当前渠道不支持会话转移")
            return
        self._pending_transfer_label = label
        self._start_action(
            "transfer",
            lambda: sender.transfer_to_cs(
                shop_id, account_user_id, customer_uid, cs_uid
            ),
        )

    def _on_action_done(self, action: str, result: Any, error_type: str):
        self._action_in_progress = False
        self._set_composer_enabled(bool(self._active_conversation))
        if error_type:
            self._show_notice("error", f"操作失败（{error_type}）")
            self.refresh(force=True)
            return

        if action == "load_cs":
            scope = self._conversation_action_scope()
            if not scope:
                return
            options = _available_cs_options(result, scope[1], scope[2])
            if not options:
                self._show_notice("warning", "当前没有其他可接管的客服")
                return
            labels = [label for label, _uid in options]
            selected, accepted = QInputDialog.getItem(
                self, "转移会话", "选择接管客服：", labels, 0, False
            )
            if accepted and selected:
                selected_index = labels.index(selected)
                self._start_transfer(options[selected_index][1], selected)
            return

        succeeded = isinstance(result, dict) and result.get("success") is True
        if action == "send":
            if succeeded:
                if self.reply_input.toPlainText().strip() == self._pending_reply_text:
                    self.reply_input.clear()
                self._show_notice("success", "消息已发送")
            else:
                self._show_notice("error", "消息发送失败，请检查客服账号状态")
        elif action == "transfer":
            if succeeded:
                self._show_notice(
                    "success", f"会话已转移给 {self._pending_transfer_label}"
                )
            else:
                self._show_notice("error", "会话转移失败，请检查目标客服状态")
        self.refresh(force=True)
