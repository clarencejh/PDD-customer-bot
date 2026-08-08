"""基于 Qt 系统托盘的 Windows/macOS 原生通知入口。"""

from __future__ import annotations

from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from config import config
from utils.logger_loguru import get_logger
from utils.runtime_path import get_resource_path


class SystemNotificationService:
    def __init__(self) -> None:
        self.logger = get_logger("SystemNotificationService")
        self.window = None
        self.tray_icon = QSystemTrayIcon(
            QIcon(str(get_resource_path("icon/icon.ico")))
        )
        self.tray_icon.setToolTip("Agent-Customer")

        self.menu = QMenu()
        self.show_action = QAction("显示主窗口", self.menu)
        self.quit_action = QAction("退出", self.menu)
        self.show_action.triggered.connect(self.show_window)
        self.quit_action.triggered.connect(self.quit_application)
        self.menu.addAction(self.show_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)
        self.tray_icon.setContextMenu(self.menu)
        self.tray_icon.activated.connect(self._on_activated)

    def attach_window(self, window) -> None:
        self.window = window

    def refresh_visibility(self, enabled: bool | None = None) -> None:
        if enabled is None:
            enabled = config.get("system_notifications", True)
        # 托盘是后台运行和退出的入口，不应随通知开关隐藏。
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()
        else:
            self.tray_icon.hide()
            if enabled:
                self.logger.warning("当前桌面环境不支持系统托盘通知")

    def notify(
        self,
        title: str,
        message: str,
        level: str = "information",
        duration_ms: int = 5000,
    ) -> bool:
        if not config.get("system_notifications", True):
            return False
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.logger.warning("系统通知发送失败：系统托盘不可用")
            return False
        if not self.tray_icon.isVisible():
            self.tray_icon.show()
        icons = {
            "information": QSystemTrayIcon.MessageIcon.Information,
            "warning": QSystemTrayIcon.MessageIcon.Warning,
            "critical": QSystemTrayIcon.MessageIcon.Critical,
        }
        self.tray_icon.showMessage(
            title,
            message,
            icons.get(level, QSystemTrayIcon.MessageIcon.Information),
            duration_ms,
        )
        return True

    def show_window(self) -> None:
        if self.window is None:
            return
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def quit_application(self) -> None:
        if self.window is not None:
            request_quit = getattr(self.window, "request_quit", None)
            if request_quit is not None:
                request_quit()
            else:
                self.window.close()
            return
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def shutdown(self) -> None:
        self.tray_icon.hide()

    def _on_activated(self, reason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.show_window()


def get_system_notifier() -> SystemNotificationService | None:
    app = QApplication.instance()
    return getattr(app, "system_notifier", None) if app is not None else None


def notify_system(title: str, message: str, level: str = "information") -> bool:
    notifier = get_system_notifier()
    if notifier is None:
        return False
    return notifier.notify(title, message, level)


__all__ = [
    "SystemNotificationService",
    "get_system_notifier",
    "notify_system",
]
