"""Windows 和 macOS 当前用户登录启动注册。"""

from __future__ import annotations

import platform
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any

from utils.runtime_path import get_base_path, is_frozen


APP_NAME = "Agent-Customer"
MACOS_LAUNCH_AGENT_ID = "com.agentcustomer.desktop"
WINDOWS_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class StartupRegistrationError(RuntimeError):
    """登录启动注册失败。"""


class StartupService:
    def __init__(
        self,
        platform_name: str | None = None,
        home_dir: Path | None = None,
        executable: Path | None = None,
        app_script: Path | None = None,
        frozen: bool | None = None,
        registry_module: Any = None,
    ) -> None:
        self.platform_name = platform_name or platform.system()
        self.home_dir = Path(home_dir) if home_dir is not None else Path.home()
        self.executable = (
            Path(executable) if executable is not None else Path(sys.executable)
        )
        self.app_script = (
            Path(app_script)
            if app_script is not None
            else get_base_path() / "app.py"
        )
        self.frozen = is_frozen() if frozen is None else frozen
        self.registry_module = registry_module

    def is_supported(self) -> bool:
        return self.platform_name in {"Windows", "Darwin"}

    def launch_arguments(self) -> list[str]:
        if self.frozen:
            return [str(self.executable)]
        return [str(self.executable), str(self.app_script)]

    def working_directory(self) -> Path:
        return self.executable.parent if self.frozen else self.app_script.parent

    def is_enabled(self) -> bool:
        if self.platform_name == "Windows":
            expected = subprocess.list2cmdline(self.launch_arguments())
            return self._windows_value() == expected
        if self.platform_name == "Darwin":
            path = self._macos_plist_path()
            if not path.exists():
                return False
            try:
                with path.open("rb") as file:
                    payload = plistlib.load(file)
                return (
                    payload.get("Label") == MACOS_LAUNCH_AGENT_ID
                    and payload.get("ProgramArguments") == self.launch_arguments()
                    and payload.get("RunAtLoad") is True
                )
            except (OSError, plistlib.InvalidFileException):
                return False
        return False

    def set_enabled(self, enabled: bool) -> None:
        if self.platform_name == "Windows":
            self._set_windows_enabled(enabled)
            return
        if self.platform_name == "Darwin":
            self._set_macos_enabled(enabled)
            return
        raise StartupRegistrationError(f"当前系统不支持登录启动: {self.platform_name}")

    def _registry(self):
        if self.registry_module is not None:
            return self.registry_module
        try:
            import winreg
        except ImportError as exc:
            raise StartupRegistrationError("当前环境无法访问 Windows 注册表") from exc
        return winreg

    def _windows_value(self) -> str | None:
        registry = self._registry()
        try:
            with registry.OpenKey(
                registry.HKEY_CURRENT_USER,
                WINDOWS_RUN_KEY,
                0,
                registry.KEY_READ,
            ) as key:
                value, _ = registry.QueryValueEx(key, APP_NAME)
                return str(value)
        except OSError:
            return None

    def _set_windows_enabled(self, enabled: bool) -> None:
        registry = self._registry()
        try:
            with registry.CreateKeyEx(
                registry.HKEY_CURRENT_USER,
                WINDOWS_RUN_KEY,
                0,
                registry.KEY_SET_VALUE,
            ) as key:
                if enabled:
                    registry.SetValueEx(
                        key,
                        APP_NAME,
                        0,
                        registry.REG_SZ,
                        subprocess.list2cmdline(self.launch_arguments()),
                    )
                else:
                    try:
                        registry.DeleteValue(key, APP_NAME)
                    except FileNotFoundError:
                        pass
        except OSError as exc:
            action = "启用" if enabled else "关闭"
            raise StartupRegistrationError(f"{action} Windows 登录启动失败") from exc

    def _macos_plist_path(self) -> Path:
        return (
            self.home_dir
            / "Library"
            / "LaunchAgents"
            / f"{MACOS_LAUNCH_AGENT_ID}.plist"
        )

    def _set_macos_enabled(self, enabled: bool) -> None:
        path = self._macos_plist_path()
        try:
            if not enabled:
                path.unlink(missing_ok=True)
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "Label": MACOS_LAUNCH_AGENT_ID,
                "ProgramArguments": self.launch_arguments(),
                "WorkingDirectory": str(self.working_directory()),
                "RunAtLoad": True,
                "KeepAlive": False,
                "ProcessType": "Interactive",
            }
            temporary_path = path.with_suffix(".tmp")
            with temporary_path.open("wb") as file:
                plistlib.dump(payload, file, sort_keys=True)
            temporary_path.replace(path)
        except OSError as exc:
            action = "启用" if enabled else "关闭"
            raise StartupRegistrationError(f"{action} macOS 登录启动失败") from exc


startup_service = StartupService()


__all__ = [
    "APP_NAME",
    "MACOS_LAUNCH_AGENT_ID",
    "StartupRegistrationError",
    "StartupService",
    "startup_service",
]
