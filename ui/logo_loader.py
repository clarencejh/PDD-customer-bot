"""安全加载店铺 Logo，避免卡片销毁时连带销毁工作线程。"""

from __future__ import annotations

import uuid
from urllib.parse import urlsplit, urlunsplit

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QPainter, QPainterPath, QPixmap

from utils.logger_loguru import get_logger
from utils.safe_image_fetch import fetch_image


logger = get_logger("ShopLogoLoader")


def normalize_logo_url(url: str) -> str:
    """将平台返回的 HTTP/协议相对图片地址安全升级为 HTTPS。"""
    value = str(url or "").strip()
    if value.startswith("//"):
        value = f"https:{value}"
    parsed = urlsplit(value)
    if parsed.scheme.lower() == "http":
        parsed = parsed._replace(scheme="https")
        value = urlunsplit(parsed)
    return value


class _LogoResultBus(QObject):
    finished = pyqtSignal(str, object, str)


_result_bus = _LogoResultBus()


class _LogoFetchTask(QRunnable):
    def __init__(self, request_id: str, url: str):
        super().__init__()
        self.request_id = request_id
        self.url = url
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        try:
            image_data = fetch_image(self.url)
            _result_bus.finished.emit(self.request_id, image_data, "")
        except Exception as exc:
            _result_bus.finished.emit(self.request_id, b"", type(exc).__name__)


class ShopLogoLoader(QObject):
    """用全局线程池加载图片，并在 GUI 线程中生成圆形 QPixmap。"""

    logo_loaded = pyqtSignal(QPixmap)

    def __init__(self, url: str, parent: QObject | None = None):
        super().__init__(parent)
        self.url = normalize_logo_url(url)
        self.request_id = ""
        self._active = False

    def start(self):
        if self._active:
            return
        self.request_id = uuid.uuid4().hex
        self._active = True
        _result_bus.finished.connect(self._on_finished)
        QThreadPool.globalInstance().start(_LogoFetchTask(self.request_id, self.url))

    @pyqtSlot(str, object, str)
    def _on_finished(self, request_id: str, image_data: object, error_type: str):
        if request_id != self.request_id:
            return
        self._disconnect_bus()
        self._active = False

        if error_type:
            logger.debug(f"shop logo unavailable: error_type={error_type}")
            self.logo_loaded.emit(QPixmap())
            return

        pixmap = QPixmap()
        if not pixmap.loadFromData(bytes(image_data)) or pixmap.isNull():
            logger.debug("shop logo unavailable: error_type=InvalidImage")
            self.logo_loaded.emit(QPixmap())
            return

        size = 60
        circular_pixmap = QPixmap(size, size)
        circular_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(circular_pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addEllipse(0, 0, size, size)
        painter.setClipPath(path)
        scaled = pixmap.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap(0, 0, scaled)
        painter.end()
        self.logo_loaded.emit(circular_pixmap)

    def _disconnect_bus(self):
        try:
            _result_bus.finished.disconnect(self._on_finished)
        except (RuntimeError, TypeError):
            pass
