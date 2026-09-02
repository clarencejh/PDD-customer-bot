"""店铺运营工作台。

账号管理和自动回复共享同一张高密度列表，避免操作员在两个页面间切换。
旧的 ``AutoReplyUI`` 名称保留为兼容别名，运行时状态仍由原管理器负责。
"""

from collections import defaultdict
from typing import Any, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QMessageBox,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    CheckBox,
    ComboBox,
    FluentIcon as FIF,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TableWidget,
)

from config import config
from service.account_service import account_service
from service.system_notification_service import notify_system
from utils.logger_loguru import get_logger
from .manager import auto_reply_manager
from .threads import (
    AccountIdentityThread,
    SetStatusThread,
)


class OperationsUI(QFrame):
    """店铺、账号和自动回复的统一运营页面。"""

    COLUMN_COUNT = 9

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.logger = get_logger("OperationsUI")
        self.accounts_data: list[dict[str, Any]] = []
        self._loaded_once = False
        self._identity_refresh_attempted = False
        self._startup_auto_reply_attempted = False
        self.identity_thread = None
        self._selected_keys: set[str] = set()
        self._status_threads: dict[str, SetStatusThread] = {}
        self._reported_ai_failures: set[str] = set()
        self._reported_connection_errors: dict[str, str] = {}
        self._hide_account_info = True
        self._build_ui()

        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self.refresh_runtime_state)
        self.stats_timer.start(5000)
        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self.refresh_runtime_state)
        self.sync_timer.start(10000)
        QTimer.singleShot(300, self._maybe_load)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(18)

        title_row = QHBoxLayout()
        title_area = QVBoxLayout()
        title_area.setSpacing(3)
        title_area.addWidget(SubtitleLabel("店铺运营"))
        self.summary_label = CaptionLabel("加载中")
        self.summary_label.setStyleSheet("color: #667085;")
        title_area.addWidget(self.summary_label)
        title_row.addLayout(title_area)
        title_row.addStretch()

        self.refresh_btn = PushButton("刷新")
        self.refresh_btn.setIcon(FIF.UPDATE)
        self.refresh_btn.clicked.connect(self.load_accounts)
        self.add_btn = PrimaryPushButton("添加账号")
        self.add_btn.setIcon(FIF.ADD)
        self.add_btn.clicked.connect(self.add_account)
        self.start_all_btn = PushButton("批量启动")
        self.start_all_btn.setIcon(FIF.PLAY_SOLID)
        self.start_all_btn.clicked.connect(self.start_selected)
        self.stop_all_btn = PushButton("批量停止")
        self.stop_all_btn.setIcon(FIF.CANCEL)
        self.stop_all_btn.clicked.connect(self.stop_selected)
        self.account_privacy_btn = PushButton("显示账户信息")
        self.account_privacy_btn.setIcon(FIF.VIEW)
        self.account_privacy_btn.setToolTip("切换店铺名称和账号信息的显示方式")
        self.account_privacy_btn.clicked.connect(self._toggle_account_info)
        self.refresh_btn.setFixedSize(90, 40)
        self.add_btn.setFixedSize(120, 40)
        self.start_all_btn.setFixedSize(120, 40)
        self.stop_all_btn.setFixedSize(120, 40)
        self.account_privacy_btn.setFixedSize(130, 40)
        for button in (
            self.refresh_btn,
            self.add_btn,
            self.start_all_btn,
            self.stop_all_btn,
            self.account_privacy_btn,
        ):
            title_row.addWidget(button)
        layout.addLayout(title_row)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)
        self.shop_filter = ComboBox()
        self.shop_filter.setFixedWidth(210)
        self.shop_filter.currentIndexChanged.connect(self.refresh_table)
        self.platform_filter = ComboBox()
        self.platform_filter.setFixedWidth(140)
        self.platform_filter.addItems(["全部平台状态", "在线", "离线", "未验证", "休息"])
        self.platform_filter.currentIndexChanged.connect(self.refresh_table)
        self.reply_filter = ComboBox()
        self.reply_filter.setFixedWidth(140)
        self.reply_filter.addItems(["全部回复状态", "运行中", "未启动", "连接中", "异常"])
        self.reply_filter.currentIndexChanged.connect(self.refresh_table)
        self.search_edit = LineEdit()
        self.search_edit.setPlaceholderText("搜索店铺、账号或用户 ID")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(240)
        self.search_edit.textChanged.connect(self.refresh_table)
        self.only_error = CheckBox("仅看异常")
        self.only_error.stateChanged.connect(self.refresh_table)
        self.select_all_btn = PushButton("全选")
        self.select_all_btn.setIcon(FIF.CHECKBOX)
        self.select_all_btn.setFixedSize(100, 34)
        self.select_all_btn.clicked.connect(self.toggle_select_all)
        filter_row.addWidget(self.shop_filter)
        filter_row.addWidget(self.platform_filter)
        filter_row.addWidget(self.reply_filter)
        filter_row.addWidget(self.search_edit, 1)
        filter_row.addWidget(self.only_error)
        filter_row.addWidget(self.select_all_btn)
        layout.addLayout(filter_row)

        self.table = TableWidget(self)
        self.table.setRowCount(0)
        self.table.setColumnCount(self.COLUMN_COUNT)
        self.table.setHorizontalHeaderLabels(
            ["选择", "店铺 / 账号", "身份", "平台状态", "自动回复", "最近心跳", "今日消息", "健康", "操作"]
        )
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 48)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        column_widths = {2: 100, 3: 100, 4: 104, 5: 90, 6: 78, 7: 112, 8: 188}
        for column, width in column_widths.items():
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(column, width)
        self.table.itemChanged.connect(self._on_item_changed_once)
        layout.addWidget(self.table, 1)
        self.setObjectName("店铺运营")

    def showEvent(self, event):
        super().showEvent(event)
        self._maybe_load()

    def closeEvent(self, event):
        self.stats_timer.stop()
        self.sync_timer.stop()
        event.accept()

    def _maybe_load(self):
        if not self._loaded_once and self.isVisible():
            self._loaded_once = True
            self.load_accounts()

    @staticmethod
    def account_key(account: dict) -> str:
        return auto_reply_manager._account_key(account)

    @staticmethod
    def platform_status(account: dict) -> str:
        return {1: "在线", 3: "离线", 0: "休息", None: "未验证"}.get(account.get("status"), "未知")

    def reply_status(self, account: dict) -> str:
        key = self.account_key(account)
        thread = auto_reply_manager.running_accounts.get(key)
        if key in auto_reply_manager.connected_accounts:
            if account.get("last_error"):
                return "异常"
            return "运行中"
        if thread is not None and hasattr(thread, "isRunning") and thread.isRunning():
            return "连接中"
        if account.get("last_error"):
            return "异常"
        return "未启动"

    def health_status(self, account: dict, reply_status: str) -> str:
        if reply_status == "异常" or self.platform_status(account) in {"离线", "未验证"}:
            return "需关注"
        if reply_status == "连接中":
            return "处理中"
        return "正常"

    def load_accounts(self):
        try:
            self.accounts_data = account_service.get_all_accounts_with_details() or []
            for account in self.accounts_data:
                account.setdefault("last_error", "")
            valid_keys = {self.account_key(account) for account in self.accounts_data}
            self._selected_keys.intersection_update(valid_keys)
            self._populate_shop_filter()
            self.refresh_table()
            self._refresh_unknown_identities()
            self._maybe_auto_start_reply()
        except Exception as exc:
            self.logger.error(f"加载店铺运营数据失败: error_type={type(exc).__name__}")
            self.summary_label.setText("加载失败，请刷新重试")

    # 兼容旧页面公开方法，避免外部调用方随导航合并一起失效。
    def loadAccountsFromDB(self):
        self.load_accounts()

    def reloadAccounts(self):
        self.load_accounts()

    @staticmethod
    def startup_auto_reply_candidates(accounts, is_running):
        """返回本次启动时可自动开启回复的在线账号。"""
        return [
            account
            for account in accounts
            if account.get("status") == 1 and not is_running(account)
        ]

    def _maybe_auto_start_reply(self):
        if self._startup_auto_reply_attempted:
            return
        self._startup_auto_reply_attempted = True
        if not config.get("auto_start_reply", True):
            self.logger.info("已关闭启动时自动开启回复")
            return
        accounts = self.startup_auto_reply_candidates(
            self.accounts_data,
            auto_reply_manager.is_running,
        )
        if not accounts:
            self.logger.info("启动时没有可自动开启回复的在线账号")
            return
        self.logger.info(f"启动时将自动开启 {len(accounts)} 个账号的自动回复")
        self._start_auto_reply_accounts(accounts, interactive=False)

    def updateStats(self):
        self.summary_label.setText(self._summary_text())

    def onStartAllAutoReply(self):
        self.start_selected()

    def stopAllAutoReply(self):
        self.stop_selected()

    def _refresh_unknown_identities(self):
        if self._identity_refresh_attempted:
            return
        unknown = [
            account for account in self.accounts_data
            if account.get("is_main_account") is None and account.get("cookies")
        ]
        if not unknown:
            return
        self._identity_refresh_attempted = True
        self.identity_thread = AccountIdentityThread(unknown, self)
        self.identity_thread.identities_updated.connect(
            lambda count: self.load_accounts() if count else None
        )
        self.identity_thread.finished.connect(self.identity_thread.deleteLater)
        self.identity_thread.start()

    def _populate_shop_filter(self):
        current = self.shop_filter.currentData()
        self.shop_filter.blockSignals(True)
        self.shop_filter.clear()
        self.shop_filter.addItem("全部店铺")
        self.shop_filter.setItemData(0, "")
        shops = {}
        for account in self.accounts_data:
            shops[(account.get("channel_name", ""), account.get("shop_id", ""))] = account.get("shop_name") or account.get("shop_id", "")
        for (channel, shop_id), shop_name in sorted(shops.items(), key=lambda item: item[1]):
            index = self.shop_filter.count()
            self.shop_filter.addItem(
                f"{self._display_shop_name(shop_name)} · "
                f"{self._display_account_value(shop_id)}"
            )
            self.shop_filter.setItemData(index, f"{channel}|{shop_id}")
        if current:
            index = self.shop_filter.findData(current)
            self.shop_filter.setCurrentIndex(max(index, 0))
        self.shop_filter.blockSignals(False)

    def _filtered_accounts(self):
        query = self.search_edit.text().strip().lower()
        shop_scope = self.shop_filter.currentData() or ""
        platform_scope = self.platform_filter.currentText()
        reply_scope = self.reply_filter.currentText()
        only_error = self.only_error.isChecked()
        visible = []
        for account in self.accounts_data:
            platform = self.platform_status(account)
            reply = self.reply_status(account)
            health = self.health_status(account, reply)
            if shop_scope and f"{account.get('channel_name')}|{account.get('shop_id')}" != shop_scope:
                continue
            if platform_scope not in {"全部平台状态", platform}:
                continue
            if reply_scope not in {"全部回复状态", reply}:
                continue
            if only_error and health == "正常":
                continue
            haystack = " ".join(str(account.get(key, "")) for key in ("shop_name", "shop_id", "username", "user_id")).lower()
            if query and query not in haystack:
                continue
            visible.append(account)
        return visible

    def _toggle_account_info(self) -> None:
        self._hide_account_info = not self._hide_account_info
        self.account_privacy_btn.setText(
            "显示账户信息" if self._hide_account_info else "隐藏账户信息"
        )
        self.account_privacy_btn.setIcon(
            FIF.VIEW if self._hide_account_info else FIF.HIDE
        )
        self._populate_shop_filter()
        self.refresh_table()

    def _display_shop_name(self, value: str) -> str:
        value = str(value or "")
        if not self._hide_account_info:
            return value
        if len(value) <= 2:
            return "*" * len(value)
        return f"{value[:2]}*****"

    def _display_account_value(self, value: str) -> str:
        value = str(value or "")
        if not self._hide_account_info:
            return value
        if not value:
            return ""
        return f"{value[:2]}*****"

    def refresh_table(self, *_args):
        selected = set(self._selected_keys)
        self.table.setRowCount(0)
        grouped = defaultdict(list)
        for account in self._filtered_accounts():
            grouped[(account.get("channel_name", ""), account.get("shop_id", ""))].append(account)
        row = 0
        for (channel, shop_id), accounts in sorted(grouped.items(), key=lambda item: item[1][0].get("shop_name", "")):
            shop_name = self._display_shop_name(accounts[0].get("shop_name") or shop_id)
            running = sum(self.reply_status(account) == "运行中" for account in accounts)
            errors = sum(self.health_status(account, self.reply_status(account)) != "正常" for account in accounts)
            self.table.insertRow(row)
            self._set_item(row, 0, "", enabled=False)
            self._set_item(
                row,
                1,
                f"{shop_name}  ·  {self._display_account_value(shop_id)}",
                bold=True,
            )
            self._set_item(row, 2, f"{len(accounts)} 个账号")
            self._set_item(row, 3, "店铺汇总")
            self._set_item(row, 4, f"{running}/{len(accounts)} 运行")
            self._set_item(row, 5, "--")
            self._set_item(row, 6, "--")
            self._set_item(row, 7, f"{errors} 个需关注" if errors else "正常")
            self._set_action(row, None, shop_scope=(channel, shop_id))
            self.table.setRowHeight(row, 34)
            row += 1
            for account in accounts:
                self.table.insertRow(row)
                key = self.account_key(account)
                checkbox = QTableWidgetItem()
                checkbox.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                checkbox.setCheckState(Qt.CheckState.Checked if key in selected else Qt.CheckState.Unchecked)
                checkbox.setData(Qt.ItemDataRole.UserRole, key)
                self.table.setItem(row, 0, checkbox)
                self._set_item(
                    row,
                    1,
                    "    " + self._display_account_value(account.get("username", ""))
                    + "\n    " + self._display_account_value(account.get("user_id", "")),
                )
                self._set_item(row, 2, self._identity_text(account.get("is_main_account")))
                self._set_item(row, 3, self.platform_status(account))
                reply = self.reply_status(account)
                self._set_item(row, 4, reply)
                self._set_item(row, 5, "已连接" if reply == "运行中" else "--")
                self._set_item(row, 6, "--")
                self._set_item(row, 7, self.health_status(account, reply))
                self._set_action(row, account)
                self.table.setRowHeight(row, 48)
                row += 1
        if not grouped:
            self.table.insertRow(0)
            message = "暂无账号，点击右上角“添加账号”开始接入。" if not self.accounts_data else "没有符合当前筛选条件的账号。"
            self._set_item(0, 1, message)
            self.table.setSpan(0, 1, 1, self.COLUMN_COUNT - 1)
            self.table.setRowHeight(0, 52)
        has_selection = bool(self._selected_accounts())
        self.start_all_btn.setEnabled(has_selection)
        self.stop_all_btn.setEnabled(has_selection)
        self._sync_select_all_button()
        self.summary_label.setText(self._summary_text())

    def _on_item_changed_once(self, item):
        if item.column() != 0:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if not key:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._selected_keys.add(key)
        else:
            self._selected_keys.discard(key)
        enabled = bool(self._selected_accounts())
        self.start_all_btn.setEnabled(enabled)
        self.stop_all_btn.setEnabled(enabled)
        self._sync_select_all_button()

    def toggle_select_all(self):
        visible_keys = {self.account_key(account) for account in self._filtered_accounts()}
        if not visible_keys:
            return
        if visible_keys.issubset(self._selected_keys):
            self._selected_keys.difference_update(visible_keys)
        else:
            self._selected_keys.update(visible_keys)
        self.refresh_table()

    def _sync_select_all_button(self):
        visible_keys = {self.account_key(account) for account in self._filtered_accounts()}
        all_selected = bool(visible_keys) and visible_keys.issubset(self._selected_keys)
        self.select_all_btn.setText("取消全选" if all_selected else "全选")
        self.select_all_btn.setIcon(FIF.CLEAR_SELECTION if all_selected else FIF.CHECKBOX)
        self.select_all_btn.setEnabled(bool(visible_keys))

    def _set_item(self, row, column, text, bold=False, enabled=True):
        item = QTableWidgetItem(str(text))
        item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignLeft if column in (1, 7) else Qt.AlignmentFlag.AlignCenter))
        if bold:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        if not enabled:
            item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.table.setItem(row, column, item)

    def _set_action(self, row, account, shop_scope=None):
        widget = QWidget()
        box = QHBoxLayout(widget)
        box.setContentsMargins(5, 5, 5, 5)
        box.setSpacing(5)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if account is None:
            button = PushButton("只看本店")
            button.clicked.connect(lambda: self._focus_shop(shop_scope))
        else:
            reply = self.reply_status(account)
            platform = self.platform_status(account)
            if platform != "在线":
                button = PrimaryPushButton("验证")
                button.setIcon(FIF.SYNC)
                button.clicked.connect(lambda: self.verify_account(account))
            else:
                stopping = reply in {"运行中", "连接中"}
                button = PrimaryPushButton("停止" if reply == "运行中" else "取消" if stopping else "启动")
                button.setIcon(FIF.CANCEL if stopping else FIF.PLAY_SOLID)
                button.clicked.connect(lambda: self.toggle_reply(account))
            more = PushButton("更多")
            more.setFixedSize(72, 30)
            more.clicked.connect(lambda checked=False, data=account, anchor=more: self._show_account_menu(data, anchor))
            box.addWidget(more)
        button.setFixedSize(88 if account is not None else 100, 30)
        box.addWidget(button)
        self.table.setCellWidget(row, 8, widget)

    def _show_account_menu(self, account, anchor):
        menu = QMenu(self)
        edit_action = menu.addAction("编辑账号")
        verify_action = menu.addAction("重新验证")
        menu.addSeparator()
        delete_action = menu.addAction("删除账号")
        selected = menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        if selected == edit_action:
            self.edit_account(account)
        elif selected == verify_action:
            self.verify_account(account)
        elif selected == delete_action:
            self.delete_account(account)

    def _set_platform_status(self, account: dict, target_status: int) -> None:
        """Set PDD online/offline state and refresh the table after success."""
        key = self.account_key(account)
        active = self._status_threads.get(key)
        if active is not None and active.isRunning():
            return

        thread = SetStatusThread(account, target_status)
        self._status_threads[key] = thread
        thread.status_set_success.connect(self._on_platform_status_success)
        thread.status_set_failed.connect(self._on_platform_status_failed)
        thread.finished.connect(lambda key=key: self._status_threads.pop(key, None))
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _on_platform_status_success(self, account: dict, target_status: int) -> None:
        account["status"] = target_status
        status_text = "在线" if target_status == 1 else "离线"
        self.logger.info(
            f"账号 {account.get('username', account.get('user_id', ''))} 已设置为{status_text}"
        )
        self.load_accounts()

    def _on_platform_status_failed(self, account: dict, error_message: str) -> None:
        self.logger.warning(
            f"账号 {account.get('username', account.get('user_id', ''))} 平台状态设置失败: {error_message}"
        )
        QMessageBox.warning(
            self,
            "平台状态设置失败",
            f"账号 {account.get('username', account.get('user_id', ''))}：{error_message}",
        )

    def _focus_shop(self, scope):
        if not scope:
            return
        self.shop_filter.setCurrentIndex(self.shop_filter.findData(f"{scope[0]}|{scope[1]}"))

    @staticmethod
    def _identity_text(value):
        return {True: "主账号", False: "子账号", None: "待识别"}.get(value, "待识别")

    def _summary_text(self):
        total = len(self.accounts_data)
        online = sum(self.platform_status(a) == "在线" for a in self.accounts_data)
        running = sum(self.reply_status(a) == "运行中" for a in self.accounts_data)
        attention = sum(self.health_status(a, self.reply_status(a)) != "正常" for a in self.accounts_data)
        return f"{len({(a.get('channel_name'), a.get('shop_id')) for a in self.accounts_data})} 个店铺 · {total} 个账号 · 平台在线 {online} · 回复运行 {running} · 需关注 {attention}"

    def refresh_runtime_state(self):
        if self.accounts_data:
            self.refresh_table()

    def _selected_accounts(self):
        return [a for a in self.accounts_data if self.account_key(a) in self._selected_keys]

    def start_selected(self):
        accounts = self._selected_accounts()
        eligible = [a for a in accounts if a.get("status") == 1 and not auto_reply_manager.is_running(a)]
        if not eligible:
            QMessageBox.information(self, "没有可启动账号", "请先选择在线且未运行自动回复的账号。")
            return
        self._start_auto_reply_accounts(eligible)

    def stop_selected(self):
        accounts = [a for a in self._selected_accounts() if auto_reply_manager.is_running(a)]
        if not accounts:
            QMessageBox.information(self, "没有运行中的账号", "当前选择中没有正在运行的自动回复。")
            return
        if QMessageBox.question(self, "确认批量停止", f"将停止 {len(accounts)} 个账号的自动回复，是否继续？") != QMessageBox.StandardButton.Yes:
            return
        for account in accounts:
            auto_reply_manager.stop_auto_reply(account)
        self.refresh_runtime_state()

    def toggle_reply(self, account):
        if auto_reply_manager.is_running(account):
            auto_reply_manager.stop_auto_reply(account)
            self.refresh_runtime_state()
        elif account.get("status") != 1:
            QMessageBox.warning(self, "无法启动", "账号必须先验证并处于在线状态。")
        else:
            self._start_auto_reply_accounts([account])

    def _start_auto_reply_accounts(self, accounts, interactive=True):
        """Start platform connections without making LLM health a prerequisite."""
        started = 0
        for account in accounts:
            connection_failed = (
                (lambda error, data=account: self._on_reply_failed(data, error))
                if interactive
                else (lambda error, data=account: self._on_startup_reply_failed(data, error))
            )
            if auto_reply_manager.start_auto_reply(
                account,
                on_connection_success=lambda data=account: self._on_reply_connected(data),
                on_connection_failed=connection_failed,
                on_ai_service_failed=lambda error, data=account: self._on_ai_failed(data, error),
            ):
                started += 1
        self.refresh_runtime_state()
        if interactive and len(accounts) > 1:
            QMessageBox.information(self, "操作已提交", f"已发起 {started} / {len(accounts)} 个账号的连接。")

    def _on_reply_failed(self, account, error):
        account["last_error"] = error
        self.refresh_runtime_state()
        key = self.account_key(account)
        if self._reported_connection_errors.get(key) == error:
            return
        self._reported_connection_errors[key] = error
        notify_system(
            "自动回复连接失败",
            f"账号 {account.get('username', '')}：{error}",
            "warning",
        )
        QMessageBox.warning(self, "自动回复连接失败", f"账号 {account.get('username', '')}：{error}")

    def _on_reply_connected(self, account):
        account["last_error"] = ""
        self._reported_connection_errors.pop(self.account_key(account), None)
        self._reported_ai_failures.discard(self.account_key(account))
        self.refresh_runtime_state()
        notify_system(
            "自动回复已连接",
            f"账号 {account.get('username', '')} 已开始自动回复。",
        )

    def _on_startup_reply_failed(self, account, error):
        account["last_error"] = error
        self.refresh_runtime_state()
        self.logger.warning(
            f"启动时自动开启回复连接失败: account={self.account_key(account)}, error={error}"
        )
        notify_system(
            "自动回复连接失败",
            f"账号 {account.get('username', '')}：{error}",
            "warning",
        )

    def _on_ai_failed(self, account, error):
        key = self.account_key(account)
        if key in self._reported_ai_failures:
            return
        self._reported_ai_failures.add(key)
        account["last_error"] = error
        self.refresh_runtime_state()
        notify_system(
            "AI 服务已失效",
            f"账号 {account.get('username', '')} 保持客服连接，但暂时无法自动回复：{error}",
            "critical",
        )
        QMessageBox.warning(self, "AI 服务已失效", f"账号 {account.get('username', '')} 保持客服连接，但暂时无法自动回复：{error}")

    def add_account(self):
        from ui.user_ui import AddAccountDialog, LoginThread
        dialog = AddAccountDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.add_btn.setEnabled(False)
        thread = LoginThread(dialog.getAccountInfo())
        self._add_thread = thread
        thread.login_finished.connect(self._on_add_finished)
        thread.finished.connect(lambda: self.add_btn.setEnabled(True))
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _on_add_finished(self, result: Optional[dict]):
        if not result:
            QMessageBox.warning(self, "添加失败", "登录验证失败，请检查登录信息后重试。")
            return
        try:
            channel, shop_id = result["channel_name"], result["shop_id"]
            if not account_service.get_shop(channel, shop_id):
                account_service.add_shop(channel, shop_id, result["shop_name"], result.get("shop_logo"), "由登录自动添加")
            ok = account_service.add_account(channel, shop_id, result["user_id"], result["username"], result["password"], result.get("cookies"), result.get("is_main_account"))
            if ok:
                # 新账号登录成功后，必须同步平台客服状态；仅保存 cookies
                # 或建立 WebSocket 不能让平台把新客户分配给该账号。
                self._set_platform_status(
                    {
                        **result,
                        "channel_name": channel,
                        "shop_id": shop_id,
                        "cookies": result.get("cookies"),
                    },
                    1,
                )
            QMessageBox.information(self, "添加成功", "账号已加入店铺运营列表。" if ok else "账号可能已存在，未重复添加。")
            self.load_accounts()
        except Exception as exc:
            self.logger.error(f"保存账号失败: error_type={type(exc).__name__}")
            QMessageBox.critical(self, "添加失败", "账号保存失败，请查看日志。")

    def edit_account(self, account):
        from ui.user_ui import EditAccountDialog
        dialog = EditAccountDialog(account, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.getAccountData()
        ok = account_service.update_account_info(data["channel_name"], data["shop_id"], data["user_id"], data["username"], data["password"], status=data["status"])
        if ok:
            QMessageBox.information(self, "保存成功", "账号信息已更新。")
            self.load_accounts()
        else:
            QMessageBox.warning(self, "保存失败", "账号信息未能更新。")

    def verify_account(self, account):
        from ui.user_ui import LoginThread
        key = self.account_key(account)
        active = getattr(self, "_verify_threads", {}).get(key)
        if active and active.isRunning():
            return
        if not hasattr(self, "_verify_threads"):
            self._verify_threads = {}
        thread = LoginThread(account)
        self._verify_threads[key] = thread
        thread.login_finished.connect(lambda result, data=account: self._on_verify_finished(data, result))
        thread.finished.connect(lambda key=key: self._verify_threads.pop(key, None))
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _on_verify_finished(self, account, result):
        if isinstance(result, dict):
            cookies = result.get("cookies")
            cookies_updated = account_service.update_account_cookies(
                account["channel_name"], account["shop_id"], account["user_id"], cookies
            )
            if not cookies_updated:
                QMessageBox.warning(self, "验证失败", "登录成功，但账号 cookies 保存失败。")
                self.load_accounts()
                return
            account["cookies"] = cookies
            if "is_main_account" in result:
                account_service.update_account_identity(account["channel_name"], account["shop_id"], account["user_id"], result["is_main_account"])
            # 登录成功不等于平台客服在线；必须再调用 set_csstatus(1)，否则
            # WebSocket 虽然可收发已有会话，但平台不会把新客分配给该账号。
            self._set_platform_status(account, 1)
            QMessageBox.information(self, "验证成功", f"账号 {account.get('username', '')} 登录成功，登录态已保存。")
        else:
            account_service.update_account_status(account["channel_name"], account["shop_id"], account["user_id"], 3)
            QMessageBox.warning(self, "验证失败", f"账号 {account.get('username', '')} 登录验证失败。")
        self.load_accounts()

    def delete_account(self, account):
        if auto_reply_manager.is_running(account):
            QMessageBox.warning(self, "无法删除", "请先停止该账号的自动回复。")
            return
        answer = QMessageBox.question(
            self,
            "确认删除账号",
            f"将删除账号 {account.get('username', '')}。历史会话不会随账号一起删除，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if account_service.delete_account(account["channel_name"], account["shop_id"], account["user_id"]):
            self._selected_keys.discard(self.account_key(account))
            self.load_accounts()
        else:
            QMessageBox.warning(self, "删除失败", "账号未能删除，请查看日志。")


# 旧名称作为兼容入口，主窗口现在只注册一个店铺运营页面。
AutoReplyUI = OperationsUI

__all__ = ["OperationsUI", "AutoReplyUI"]
