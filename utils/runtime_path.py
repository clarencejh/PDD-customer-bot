"""
运行时路径处理工具
用于处理打包后的资源文件路径和临时目录创建
"""

import os
import platform
import sys
import copy
import shutil
from pathlib import Path
from typing import Union


def is_frozen() -> bool:
    """
    检查程序是否被打包（使用 PyInstaller 或类似工具）

    Returns:
        bool: 如果是打包后的程序返回 True，否则返回 False
    """
    return getattr(sys, 'frozen', False)


def get_base_path() -> Path:
    """
    获取应用程序的基础路径

    Returns:
        Path: 开发环境下返回项目根目录，打包环境下返回可执行文件所在目录
    """
    if is_frozen():
        # PyInstaller 打包后的路径
        return Path(sys.executable).parent
    else:
        # 开发环境下的路径
        return Path(__file__).resolve().parents[1]


def get_data_path() -> Path:
    """Return the writable per-user data directory."""
    if not is_frozen():
        return get_base_path()
    return get_user_data_path()


def get_user_data_path(
    platform_name: str | None = None,
    environ: dict[str, str] | None = None,
    home_dir: Path | None = None,
) -> Path:
    """Return the conventional per-user application data directory."""
    platform_name = platform_name or platform.system()
    environ = os.environ if environ is None else environ
    home_dir = Path.home() if home_dir is None else Path(home_dir)
    if platform_name == "Windows":
        root = environ.get("LOCALAPPDATA")
        return (
            Path(root) if root else home_dir / "AppData" / "Local"
        ) / "Agent-Customer"
    if platform_name == "Darwin":
        return home_dir / "Library" / "Application Support" / "Agent-Customer"
    root = environ.get("XDG_DATA_HOME")
    return (Path(root) if root else home_dir / ".local" / "share") / "Agent-Customer"


def resolve_data_path(path: Union[str, Path]) -> Path:
    """Resolve a configured path inside the writable application data root."""
    candidate = Path(path)
    if not candidate.is_absolute():
        target = get_data_path() / candidate
        if is_frozen() and not target.exists() and candidate.suffix.lower() in {
            ".db", ".sqlite", ".sqlite3"
        }:
            legacy = get_base_path() / candidate
            if legacy.exists() and legacy.is_file():
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(legacy, target)
                    for suffix in ("-wal", "-shm"):
                        sidecar = Path(str(legacy) + suffix)
                        if sidecar.exists() and sidecar.is_file():
                            shutil.copy2(sidecar, Path(str(target) + suffix))
                except OSError:
                    # Do not silently open a new empty database when migration
                    # cannot be completed.
                    return legacy
        candidate = target
    return candidate


def get_resource_path(relative_path: Union[str, Path]) -> Path:
    """
    获取资源文件的绝对路径

    Args:
        relative_path: 相对于项目根目录的资源路径

    Returns:
        Path: 资源文件的绝对路径

    Example:
        >>> config_path = get_resource_path("config.json")
        >>> icon_path = get_resource_path("icon/icon.ico")
    """
    base_path = get_base_path()

    # 在开发环境下，直接返回相对路径
    if not is_frozen():
        return base_path / relative_path

    # 在打包环境下，优先查找 _MEIPASS 目录（PyInstaller 临时目录）
    if hasattr(sys, '_MEIPASS'):
        resource_dir = Path(sys._MEIPASS)
        resource_path = resource_dir / relative_path

        # 如果在临时目录中找到资源，返回该路径
        if resource_path.exists():
            return resource_path

    # 否则返回可执行文件目录下的路径
    return base_path / relative_path


def get_temp_path(subpath: Union[str, Path] = "") -> Path:
    """
    获取临时目录路径

    Args:
        subpath: 临时目录下的子路径

    Returns:
        Path: 临时目录的绝对路径
    """
    if is_frozen():
        # 打包环境下，使用可执行文件目录下的 temp 文件夹
        temp_dir = get_data_path() / "temp"
    else:
        # 开发环境下，使用项目根目录下的 temp 文件夹
        temp_dir = get_data_path() / "temp"

    # 如果指定了子路径，追加到临时目录
    if subpath:
        return temp_dir / subpath

    return temp_dir


def ensure_temp_dir(subpath: Union[str, Path] = "") -> Path:
    """
    确保临时目录存在（如果不存在则创建）

    Args:
        subpath: 临时目录下的子路径

    Returns:
        Path: 创建或已存在的临时目录路径
    """
    temp_dir = get_temp_path(subpath)
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def get_config_path(config_name: str = "config.json") -> Path:
    """
    获取配置文件路径

    Args:
        config_name: 配置文件名

    Returns:
        Path: 配置文件的绝对路径
    """
    # 配置属于用户数据，打包后放到系统标准用户数据目录，避免安装目录不可写。
    target = get_data_path() / config_name
    if is_frozen() and not target.exists():
        legacy = get_base_path() / config_name
        if legacy.exists() and legacy.is_file() and legacy.resolve() != target.resolve():
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(legacy, target)
            except OSError:
                return legacy
    return target


def get_log_path() -> Path:
    """
    获取日志文件路径

    Returns:
        Path: 日志文件的绝对路径
    """
    log_dir = ensure_temp_dir("logs")
    return log_dir / "app.log"


def get_database_path(db_name: str = "agent.db") -> Path:
    """
    获取数据库文件路径

    Args:
        db_name: 数据库文件名

    Returns:
        Path: 数据库文件的绝对路径
    """
    db_dir = ensure_temp_dir()
    return db_dir / db_name


def get_vector_db_path() -> Path:
    """
    获取向量数据库路径

    Returns:
        Path: 向量数据库的绝对路径
    """
    return ensure_temp_dir("vector_db")


def get_contents_db_path() -> Path:
    """
    获取内容数据库路径

    Returns:
        Path: 内容数据库的绝对路径
    """
    return ensure_temp_dir("contents.db")



def adjust_config_for_runtime(config: dict) -> dict:
    """
    调整配置以适应运行时环境

    Args:
        config: 原始配置字典

    Returns:
        dict: 调整后的配置字典
    """
    # 创建深拷贝，避免调整嵌套路径时修改调用方配置。
    adjusted_config = copy.deepcopy(config)

    # 调整数据库路径
    if "db_path" in adjusted_config:
        adjusted_config["db_path"] = str(get_database_path())

    # 调整知识库相关路径
    if "knowledge_base" in adjusted_config:
        kb_config = adjusted_config["knowledge_base"]

        if "contents_db_path" in kb_config:
            kb_config["contents_db_path"] = str(get_contents_db_path())

        if "vector_db_path" in kb_config:
            kb_config["vector_db_path"] = str(get_vector_db_path())

    # 调整其他可能的路径配置
    path_keys = [
        "log_path",
        "cache_path",
        "data_path",
        "output_path"
    ]

    for key in path_keys:
        if key in adjusted_config:
            # 如果是相对路径，转换为绝对路径
            path = Path(adjusted_config[key])
            if not path.is_absolute():
                adjusted_config[key] = str(get_temp_path() / path.name)

    return adjusted_config


def print_runtime_info():
    """
    打印运行时环境信息（调试用）
    """
    print("=" * 50)
    print("运行时环境信息")
    print("=" * 50)
    print(f"是否打包: {is_frozen()}")
    print(f"基础路径: {get_base_path()}")
    print(f"临时目录: {get_temp_path()}")
    print(f"配置文件: {get_config_path()}")
    print(f"日志文件: {get_log_path()}")
    print(f"数据库路径: {get_database_path()}")
    print(f"向量数据库: {get_vector_db_path()}")
    print("=" * 50)


# 目录创建由应用入口按需触发，避免导入期的磁盘操作


if __name__ == "__main__":
    # 测试代码
    print_runtime_info()

    # 测试资源路径
    print("\n测试资源路径:")
    print(f"config.json: {get_resource_path('config.json')}")
    print(f"icon/icon.ico: {get_resource_path('icon/icon.ico')}")
    print(f"app.py: {get_resource_path('app.py')}")

    # 测试路径是否存在
    print("\n路径存在性检查:")
    for path in [
        get_resource_path("config.json"),
        get_resource_path("icon/icon.ico"),
        get_temp_path(),
        get_config_path()
    ]:
        exists = path.exists() if path.is_file() else path.is_dir()
        print(f"{path}: {'存在' if exists else '不存在'}")
