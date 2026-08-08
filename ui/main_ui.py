from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QFrame, QHBoxLayout
from PyQt6.QtGui import QIcon
from qfluentwidgets import FluentWindow, NavigationItemPosition
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import SubtitleLabel
from utils.logger_loguru import get_logger
from utils.runtime_path import get_resource_path
import time

class Widget(QFrame):

    def __init__(self, text: str, parent=None):
        super().__init__(parent=parent)
        # 创建标题标签
        self.label = SubtitleLabel(text, self)
        # 创建水平布局
        self.hBoxLayout = QHBoxLayout(self)
        # 设置标签文本居中对齐
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 将标签添加到布局中,设置居中对齐和拉伸因子1
        self.hBoxLayout.addWidget(self.label, 1, Qt.AlignmentFlag.AlignCenter)
        # 必须给子界面设置全局唯一的对象名
        self.setObjectName(text.replace(' ', '-'))

class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        t = time.perf_counter()
        self.setWindowTitle('拼多多AI客服助手')
        self.setWindowIcon(QIcon(str(get_resource_path("icon/icon.ico"))))
        self.logger = get_logger("MainWindow")
        self.logger.info(f"  基础属性初始化: {time.perf_counter()-t:.2f}s")

        # 延迟加载的视图
        self.knowledge_view = None
        self.monitor_view = None
        self.keyword_manager_view = None
        self.log_view = None
        self.settingInterface = None
        self.about_view = None
        self.help_view = None
        self.conversation_view = None
        self._force_quit = False
        self._quit_pending = False
        self._background_notice_shown = False

        t = time.perf_counter()
        # 立即初始化导航和窗口
        self.initWindow()
        self.logger.info(f"  initWindow: {time.perf_counter()-t:.2f}s")

        # 延迟加载各个视图，让窗口先显示
        QTimer.singleShot(200, self.lazy_load_views)

    def lazy_load_views(self):
        """延迟加载各个视图，提高启动速度"""
        t0 = time.perf_counter()
        # 局部按需导入，减少启动时的重依赖加载
        t = time.perf_counter()
        from ui.auto_reply_ui import AutoReplyUI
        self.logger.info(f"  import AutoReplyUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        from ui.keyword_ui import KeywordManagerWidget
        self.logger.info(f"  import KeywordManagerWidget: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        from ui.log_ui import LogUI
        self.logger.info(f"  import LogUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        from ui.setting_ui import SettingUI
        self.logger.info(f"  import SettingUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        from ui.Knowledge_ui import KnowledgeUI
        self.logger.info(f"  import KnowledgeUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        from ui.about_ui import AboutUI
        self.logger.info(f"  import AboutUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        from ui.help_ui import HelpUI
        self.logger.info(f"  import HelpUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        from ui.conversation_ui import ConversationUI
        self.logger.info(f"  import ConversationUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        self.monitor_view = AutoReplyUI(self)
        self.logger.info(f"  AutoReplyUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        self.keyword_manager_view = KeywordManagerWidget(self)
        self.logger.info(f"  KeywordManagerWidget: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        self.log_view = LogUI(self)
        self.logger.info(f"  LogUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        self.knowledge_view = KnowledgeUI(self)
        self.logger.info(f"  KnowledgeUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        self.settingInterface = SettingUI(self)
        self.logger.info(f"  SettingUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        self.about_view = AboutUI(self)
        self.logger.info(f"  AboutUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        self.help_view = HelpUI(self)
        self.logger.info(f"  HelpUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        self.conversation_view = ConversationUI(self)
        self.logger.info(f"  ConversationUI: {time.perf_counter()-t:.2f}s")

        # 初始化导航
        self.initNavigation()
        self.logger.info(f"延迟视图初始化耗时: {time.perf_counter() - t0:.2f}s")

    # 初始化导航栏
    def initNavigation(self):
        self.navigationInterface.setExpandWidth(200)
        self.addSubInterface(self.monitor_view, FIF.SHOPPING_CART, '店铺运营')
        self.addSubInterface(self.conversation_view, FIF.MESSAGE, '对话记录')
        self.addSubInterface(self.keyword_manager_view, FIF.EDIT, '关键词管理')
        self.addSubInterface(self.knowledge_view, FIF.DOCUMENT, '知识库')
        self.addSubInterface(
            self.help_view, FIF.HELP, '帮助', NavigationItemPosition.BOTTOM
        )
        self.addSubInterface(
            self.about_view, FIF.INFO, '关于', NavigationItemPosition.BOTTOM
        )
        self.addSubInterface(self.log_view, FIF.HISTORY, '日志管理', NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.settingInterface, FIF.SETTING, '设置', NavigationItemPosition.BOTTOM)

        # 宽度与组件内部状态必须一致，否则 macOS 会显示宽侧栏但隐藏文字。
        self.navigationInterface.expand(useAni=False)


    # 初始化窗口
    def initWindow(self):
        # 先设置最小尺寸
        self.setMinimumWidth(1280)
        self.setMinimumHeight(720)
        
        # 设置默认尺寸（避免几何冲突）
        self.resize(1400, 800)
        
        # 最后最大化显示
        self.showMaximized()

    def request_quit(self):
        """从托盘发起真正退出，异步等待自动回复线程结束。"""
        if self._quit_pending:
            return
        self._force_quit = True
        self._quit_pending = True
        try:
            from ui.auto_reply_ui import auto_reply_manager
            auto_reply_manager.stop_all()
        except Exception as exc:
            self.logger.warning(f"停止自动回复失败: {exc}")
        self._wait_for_workers_to_quit()

    def _wait_for_workers_to_quit(self):
        from PyQt6.QtWidgets import QApplication
        try:
            from ui.auto_reply_ui import auto_reply_manager
            running = auto_reply_manager.get_running_count()
        except Exception:
            running = 0
        if running:
            QTimer.singleShot(100, self._wait_for_workers_to_quit)
            return
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def closeEvent(self, event):
        """关闭按钮隐藏到托盘；只有托盘菜单的退出才结束进程。"""
        from PyQt6.QtWidgets import QSystemTrayIcon
        tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        if not self._force_quit and tray_available:
            event.ignore()
            self.hide()
            if not self._background_notice_shown:
                self._background_notice_shown = True
                from service.system_notification_service import notify_system
                notify_system("Agent-Customer", "窗口已隐藏，自动回复仍在后台运行。")
            return
        if not self._force_quit:
            # 无托盘环境无法恢复隐藏窗口，直接走异步退出流程。
            event.accept()
            self.request_quit()
            return
        event.accept()
