# 后台线程模块
import asyncio
from PyQt6.QtCore import QThread, pyqtSignal
from utils.logger_loguru import get_logger
from ui.logo_loader import ShopLogoLoader
from service.llm_service import llm_error_message, test_llm_connection


LogoLoaderThread = ShopLogoLoader


def set_platform_account_status(account_data: dict, target_status: int) -> tuple[bool, str]:
    """Set the PDD platform status and persist it only after API success."""
    from Channel.pinduoduo.utils.API.Set_up_online import AccountMonitor
    from service.account_service import account_service

    channel_name = account_data.get("channel_name", "pinduoduo")
    shop_id = account_data.get("shop_id")
    user_id = account_data.get("user_id")
    cookies = account_data.get("cookies")
    if not cookies or not shop_id or not user_id:
        return False, "账号缺少 cookies 或身份信息，无法设置平台状态"

    try:
        monitor = AccountMonitor(
            cookies,
            shop_id=shop_id,
            user_id=user_id,
            channel_name=channel_name,
        )
        if not monitor.set_csstatus(target_status):
            return False, "平台状态设置失败，请检查账号登录状态和网络连接"
        if not account_service.update_account_status(
            channel_name=channel_name,
            shop_id=shop_id,
            user_id=user_id,
            status=target_status,
        ):
            return False, "平台状态已返回成功，但本地账号状态保存失败"
        return True, ""
    except Exception as exc:
        get_logger("AccountStatus").error(
            f"设置平台账号状态失败: error_type={type(exc).__name__}"
        )
        return False, "设置平台状态时发生异常，请检查账号登录状态和网络连接"


class AutoReplyThread(QThread):
    """自动回复线程 - 每个账号独立的WebSocket连接线程"""

    connection_success = pyqtSignal()  # 连接成功信号
    connection_failed = pyqtSignal(str)  # 连接失败信号
    ai_service_failed = pyqtSignal(str)  # AI 服务失效信号，仅通知商家端

    def __init__(self, account_data: dict):
        super().__init__()
        self.account_data = account_data
        self.channel = None
        self.loop = None
        self._shutdown_task = None
        self._stop_requested = False
        self.logger = get_logger("AutoReplyThread")

    def run(self):
        """启动后端 PDDChannel 引擎"""
        from Channel.pinduoduo.pdd_channel import PDDChannel

        try:
            # 为当前线程创建并设置新的事件循环
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

            # 创建 PDDChannel 实例
            self.channel = PDDChannel()
            self.channel.ai_failure_callback = self.ai_service_failed.emit

            # 定义成功和失败的回调函数
            def on_success():
                self.connection_success.emit()

            def on_failure(error_msg):
                self.connection_failed.emit(error_msg)

            # 启动引擎，并传递回调
            self._start_task = self.loop.create_task(
                self.channel.start_account(
                    shop_id=self.account_data['shop_id'],
                    user_id=self.account_data['user_id'],
                    on_success=on_success,
                    on_failure=on_failure
                )
            )

            # 保持事件循环运行，直到显式停止
            self.loop.run_forever()

        except Exception as e:
            self.logger.error(f"自动回复线程启动失败: {type(e).__name__}")
            self.connection_failed.emit("自动回复线程启动失败，请稍后重试")
        finally:
            loop = self.loop
            if loop is not None:
                try:
                    if loop.is_running():
                        loop.stop()

                    # 先在事件循环内取消并等待剩余任务，再关闭 loop，避免
                    # cleanup 协程在 loop 关闭后继续访问 asyncio 资源。
                    if not loop.is_closed():
                        pending = [
                            task for task in asyncio.all_tasks(loop)
                            if not task.done()
                        ]
                        for task in pending:
                            task.cancel()
                        if pending:
                            loop.run_until_complete(
                                asyncio.gather(*pending, return_exceptions=True)
                            )
                        loop.run_until_complete(loop.shutdown_asyncgens())
                        loop.close()
                except Exception as cleanup_error:
                    self.logger.error(
                        "自动回复线程清理失败: "
                        f"error_type={type(cleanup_error).__name__}"
                    )
                finally:
                    try:
                        if asyncio.get_event_loop() is loop:
                            asyncio.set_event_loop(None)
                    except RuntimeError:
                        pass

    async def _shutdown_async(self):
        """在工作线程自己的事件循环中完成连接和任务清理。"""
        try:
            if self.channel:
                shop_id = self.account_data.get("shop_id")
                user_id = self.account_data.get("user_id")
                if shop_id is not None and user_id is not None:
                    await asyncio.wait_for(
                        self.channel.stop_account(shop_id, user_id),
                        timeout=4.0,
                    )
                else:
                    await asyncio.wait_for(
                        self.channel.stop_all_connections(),
                        timeout=4.0,
                    )
        except asyncio.TimeoutError:
            self.logger.warning("自动回复连接清理超时，将取消剩余任务")
        except Exception as e:
            self.logger.warning(
                "自动回复连接清理失败，将取消剩余任务: "
                f"error_type={type(e).__name__}"
            )
        finally:
            current_task = asyncio.current_task()
            pending = [
                task for task in asyncio.all_tasks()
                if task is not current_task and not task.done()
            ]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

            asyncio.get_running_loop().stop()

    def stop(self):
        """停止后端引擎"""
        try:
            loop = self.loop
            if loop is None or loop.is_closed() or not loop.is_running():
                return
            if self._stop_requested:
                return

            self._stop_requested = True

            # stop() 通常从 Qt 主线程调用；所有 asyncio 对象必须回到其
            # 所属事件循环线程中操作，不能直接跨线程 cancel/set。
            def schedule_shutdown():
                if loop.is_closed():
                    return
                if self._shutdown_task is None or self._shutdown_task.done():
                    self._shutdown_task = loop.create_task(self._shutdown_async())

            loop.call_soon_threadsafe(schedule_shutdown)

        except Exception as e:
            self.logger.error(
                f"停止自动回复线程失败: error_type={type(e).__name__}"
            )

    def is_running(self) -> bool:
        """检查线程是否在运行"""
        # 实际的运行状态由 PDDChannel 内部管理，这里仅表示线程是否已启动
        return self.isRunning()


class LLMPreflightThread(QThread):
    """启动自动回复前在后台验证当前 LLM 配置。"""

    test_finished = pyqtSignal(bool, str)

    def __init__(self, llm_config: dict, parent=None):
        super().__init__(parent)
        self.llm_config = llm_config

    def run(self):
        try:
            asyncio.run(test_llm_connection(self.llm_config))
            self.test_finished.emit(True, "AI API 配置有效。")
        except Exception as exc:
            self.test_finished.emit(False, llm_error_message(exc))


class AccountIdentityThread(QThread):
    """Backfill platform-reported main/sub-account identities."""

    identities_updated = pyqtSignal(int)

    def __init__(self, accounts: list[dict], parent=None):
        super().__init__(parent)
        self.accounts = accounts

    def run(self):
        from Channel.pinduoduo.utils.API.get_user_info import GetUserInfo
        from service.account_service import account_service

        updated = 0
        for account in self.accounts:
            if account.get("is_main_account") is not None or not account.get("cookies"):
                continue
            try:
                details = GetUserInfo(account["cookies"]).get_user_details()
                if details is False or details.get("mallOwner") is None:
                    continue
                if account_service.update_account_identity(
                    account["channel_name"],
                    account["shop_id"],
                    account["user_id"],
                    bool(details["mallOwner"]),
                ):
                    updated += 1
            except Exception as exc:
                get_logger("AccountIdentityThread").warning(
                    f"账号身份识别失败: error_type={type(exc).__name__}"
                )
        self.identities_updated.emit(updated)


class SetStatusThread(QThread):
    """设置账号状态的线程"""

    status_set_success = pyqtSignal(dict, int)  # 设置成功信号
    status_set_failed = pyqtSignal(dict, str)   # 设置失败信号

    def __init__(self, account_data: dict, target_status: int):
        super().__init__()
        self.account_data = account_data
        self.target_status = target_status
        self.logger = get_logger()

    def run(self):
        """在后台线程中执行状态更新"""
        success, error = set_platform_account_status(
            self.account_data,
            self.target_status,
        )
        if success:
            self.status_set_success.emit(self.account_data, self.target_status)
        else:
            self.status_set_failed.emit(self.account_data, error)


__all__ = [
    'LogoLoaderThread', 'AutoReplyThread', 'LLMPreflightThread',
    'AccountIdentityThread', 'SetStatusThread',
]
