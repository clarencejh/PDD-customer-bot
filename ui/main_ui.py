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
        self.user_manager_view = None
        self.log_view = None
        self.settingInterface = None
        self.about_view = None

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
        from ui.user_ui import UserManagerWidget
        self.logger.info(f"  import UserManagerWidget: {time.perf_counter()-t:.2f}s")
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
        self.monitor_view = AutoReplyUI(self)
        self.logger.info(f"  AutoReplyUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        self.keyword_manager_view = KeywordManagerWidget(self)
        self.logger.info(f"  KeywordManagerWidget: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        self.user_manager_view = UserManagerWidget(self)
        self.logger.info(f"  UserManagerWidget: {time.perf_counter()-t:.2f}s")
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

        # 初始化导航
        self.initNavigation()
        self.logger.info(f"延迟视图初始化耗时: {time.perf_counter() - t0:.2f}s")

    # 初始化导航栏
    def initNavigation(self):
        self.navigationInterface.setExpandWidth(200)
        self.addSubInterface(self.monitor_view, FIF.CHAT, '自动回复')
        self.addSubInterface(self.keyword_manager_view, FIF.EDIT, '关键词管理')
        self.addSubInterface(self.user_manager_view, FIF.PEOPLE, '账号管理')
        self.addSubInterface(self.knowledge_view, FIF.DOCUMENT, '知识库')
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

    def closeEvent(self, a0):
        """ 重写窗口关闭事件，确保后台线程安全退出 """

        # 停止所有自动回复线程
        try:
            from ui.auto_reply_ui import auto_reply_manager
            auto_reply_manager.stop_all()
        except Exception:
            pass

        super().closeEvent(a0) 
