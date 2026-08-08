# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Agent-Customer
生成命令: pyinstaller scripts/agent_customer.spec
"""

import sys
import os
from pathlib import Path

block_cipher = None

# 项目根目录（spec 文件位于 scripts/ 目录，上两级为项目根目录）
if '__file__' in globals():
    _spec_dir = Path(os.path.abspath(__file__)).parent
    PROJECT_ROOT = _spec_dir.parent
elif len(sys.argv) > 0:
    # fallback: 从命令行参数推导
    PROJECT_ROOT = Path(sys.argv[0]).resolve().parent.parent
else:
    # last fallback: 从 cwd 推导
    PROJECT_ROOT = Path.cwd()

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from core.app_version import APP_VERSION as PROJECT_VERSION

# ================================
# Playwright 驱动打包
# ================================
# collect_all 收集 playwright/driver/ 下的 node 与 JS，否则打包后启动浏览器会
# 因驱动缺失而失败。配合 pdd_login 的 channel="chrome"，用户无需安装 Playwright 浏览器。
from PyInstaller.utils.hooks import collect_all
_pw_datas, _pw_binaries, _pw_hidden = collect_all("playwright")

# node.exe 不会进入 binaries，但会出现在 datas（目标 playwright/driver），这里显式补进 binaries
# 以便在 EXE 元信息（VirusTotal/安全软件）层面可见，行为与 datas 等价，属防御性冗余。
_pw_node = [
    (src, dst) for src, dst in _pw_datas if src.lower().endswith("node.exe")
]
_pw_binaries = list(_pw_binaries) + _pw_node

# ================================
# 基础配置
# ================================
a = Analysis(
    [str(PROJECT_ROOT / "app.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=_pw_binaries,
    datas=[
        # 图标文件
        (str(PROJECT_ROOT / "icon" / "icon.ico"), "icon"),
        (str(PROJECT_ROOT / "icon" / "Customer-Agent-qr.png"), "icon"),
    ] + _pw_datas,
    hiddenimports=[
        # === PyQt6 & Fluent Widgets ===
        "PyQt6",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PyQt6.sip",
        "qfluentwidgets",
        "qfluentwidgets.common",
        "qfluentwidgets.components",
        "qfluentwidgets.window",
        # === AI / Agent ===
        # === 嵌入器 ===
        "openai",
        "openai._models",
        "openai._client",
        "tiktoken",
        "tiktoken_ext",
        "tiktoken_ext.openai_public",
        # === 数据库 ===
        "sqlalchemy",
        "sqlalchemy.orm",
        "sqlalchemy.sql",
        "sqlalchemy.dialects.sqlite",
        # === 日志 ===
        "loguru",
        "loguru._logger",
        # === Web / 网络 ===
        "websockets",
        "websockets.client",
        "websockets.server",
        "aiohttp",
        "aiohttp.client",
        "aiohttp.web",
        "requests",
        "urllib3",
        "charset_normalizer",
        # === 浏览器自动化 ===
        "playwright",
        "playwright._impl",
        "playwright.async_api",
        # === 数据处理 ===
        "pandas",
        "pandas._libs",
        "numpy",
        "numpy.core",
        "numpy._core",
        "openpyxl",
        "openpyxl.cell",
        "openpyxl.workbook",
        "pypdf",
        "docx",
        "docx.document",
        "docx.oxml",
        # === 图像 ===
        "PIL",
        "PIL._imaging",
        # === 异步 ===
        "asyncio",
        "aiofiles",
        # === 工具类 ===
        "pydantic",
        "pydantic.fields",
        "pydantic.dataclasses",
        "pydantic.v1",
        "pydantic.v1.fields",
        "volcengine",
        "volcengine.base",
        "volcengine.viking_knowledgebase",
        "volcengine.viking_knowledgebase.Collection",
        "volcengine.viking_knowledgebase.Doc",
        # === 项目内部模块 ===
        "config",
        "core.di_container",
        "core.connection_status",
        "core.base_service",
        "database.db_manager",
        "database.models",
        "bridge.context",
        "bridge.reply",
        "bridge.sender",
        "utils.db_pragma",
        "service.account_service",
        "service.keyword_service",
        "Message.message",
        "Message.core.queue",
        "Message.core.consumer",
        "Message.core.handlers",
        "Message.handlers.base",
        "Message.handlers.ai_handler",
        "Message.handlers.keyword_handler",
        "Message.handlers.preprocessor",
        "Agent.bot",
        "Agent.CustomerAgent.custom.customer_agent",
        "Agent.CustomerAgent.custom.tool_decorator",
        "Agent.CustomerAgent.custom.session_manager",
        "Agent.CustomerAgent.tools",
        "Channel.channel",
        "Channel.pinduoduo.pdd_channel",
        "Channel.pinduoduo.pdd_message",
        "Channel.pinduoduo.pdd_login",
        "Channel.pinduoduo.utils.base_request",
        "Channel.pinduoduo.utils.API.get_token",
        "Channel.pinduoduo.utils.API.send_message",
        "Channel.pinduoduo.utils.API.get_shop_info",
        "Channel.pinduoduo.utils.API.Set_up_online",
        "Channel.pinduoduo.utils.API.product_manager",
        "Channel.pinduoduo.utils.API.get_user_info",
        "utils.logger_loguru",
        "utils.logger_config",
        "utils.resource_manager",
        "utils.path_utils",
        "utils.runtime_path",
        "utils.secret_store",
        # === 避免 pydantic v1/v2 冲突 ===
        "pydantic.errors",
        "pydantic.fields",
        "pydantic.main",
        "pydantic.schema",
        "pydantic.types",
        "pydantic.validators",
        "pydantic.class_validators",
        "pydantic.config",
        "pydantic.parse",
        "pydantic.tools",
        "pydantic.utils",
        "pydantic.validators",
        # === rich (for volcengine) ===
        "rich",
        # === 避免 importlib 静默失败 ===
        "importlib",
        "importlib.util",
        "importlib.abc",
        # === jsonschema (for openapi) ===
        # === certifi / charset ===
        "certifi",
        "charset_normalizer",
        # === httpx (for openai) ===
        "httpx",
        "httpcore",
    ] + _pw_hidden,
    hookspath=[],
    hooksconfig={},
    keys=block_cipher,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # Windows 下关闭 UPX（兼容性更好）
    console=False,        # 不显示控制台窗口（GUI 程序）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ================================
# 生成 PYZ（Python 库）
# ================================
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ================================
# 生成 EXE
# ================================
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AgentCustomer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / "icon" / "icon.ico"),
    # Windows 特定
    version="",
    description="电商AI客服助手",
    product_name="Agent-Customer",
    product_version=PROJECT_VERSION,
    company_name="",
    legal_copyright="",
    # 权限
    RequestedExecutionLevel="asInvoker",
)

# ================================
# 收集所有文件到 dist 目录
# ================================
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AgentCustomer",
)
