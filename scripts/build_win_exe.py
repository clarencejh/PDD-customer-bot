import sys, subprocess, shutil, platform, os
from pathlib import Path
import argparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.app_version import APP_VERSION

# CI（GitHub Actions windows runner）默认控制台编码是 cp1252，打印中文会
# UnicodeEncodeError。强制 stdout/stderr 用 UTF-8，保证任何机器上都能输出。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

def run(cmd):
    """运行命令"""
    print(f"执行: {' '.join(str(c) for c in cmd)}")
    subprocess.check_call([str(c) for c in cmd])

def ensure_uv():
    if shutil.which("uv") is None:
        raise RuntimeError("未检测到 uv，请先安装 uv")

def check_platform():
    """检查平台"""
    if platform.system() != "Windows":
        raise RuntimeError(
            "当前平台: " + platform.system() + "\n"
            "Windows exe 构建必须在 Windows 系统上进行！\n"
            "请在 Windows 机器上运行: python scripts/build_win_exe.py"
        )

def find_iscc():
    """定位 Inno Setup 编译器 ISCC.exe。

    查找顺序：
      1. 环境变量 ISCC（CI 或自定义路径）
      2. PATH
      3. 常见安装目录（本机用户目录 / Program Files）
    找不到返回 None。
    """
    # 1. 环境变量
    env = os.environ.get("ISCC")
    if env and Path(env).exists():
        return env
    # 2. PATH
    on_path = shutil.which("ISCC.exe") or shutil.which("ISCC")
    if on_path:
        return on_path
    # 3. 常见安装位置
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None

def ensure_iscc():
    """确保有 ISCC.exe；没有则尝试用 winget 静默安装 Inno Setup。"""
    iscc = find_iscc()
    if iscc:
        return iscc
    print("未检测到 Inno Setup，尝试用 winget 安装 ...")
    if shutil.which("winget") is None:
        raise RuntimeError(
            "未检测到 Inno Setup（ISCC.exe），且无 winget 可自动安装。\n"
            "请手动安装 Inno Setup 6: https://jrsoftware.org/isdl.php\n"
            "或设置环境变量 ISCC 指向 ISCC.exe"
        )
    run([
        "winget", "install", "--id", "JRSoftware.InnoSetup", "-e",
        "--silent", "--accept-package-agreements", "--accept-source-agreements",
    ])
    iscc = find_iscc()
    if not iscc:
        raise RuntimeError("Inno Setup 安装后仍未找到 ISCC.exe，请设置环境变量 ISCC")
    return iscc

def get_version():
    """从项目唯一版本模块读取安装包版本号。"""
    return APP_VERSION

def build_installer():
    """调用 Inno Setup 把 dist/AgentCustomer 编译成单个 setup.exe。

    通过 /DAppVersion= 把 core/app_version.py 中的版本号传给 installer.iss。
    """
    iscc = ensure_iscc()
    iss = Path("scripts") / "installer.iss"
    if not iss.exists():
        raise FileNotFoundError(f"找不到 Inno 脚本: {iss}")
    version = get_version()
    print(f"安装包版本号: {version}")
    run([iscc, f"/DAppVersion={version}", str(iss)])
    return Path("dist") / "installer", version

def main():
    parser = argparse.ArgumentParser(description="构建 Windows 发布包")
    parser.add_argument("--python", default="3.11", help="Python 版本，默认 3.11")
    parser.add_argument("--clean", action="store_true", help="构建前清理")
    parser.add_argument("--skip-installer", action="store_true",
                        help="只打包 PyInstaller onedir，不生成 Inno 安装程序")
    args = parser.parse_args()

    check_platform()
    ensure_uv()

    venv_path = Path(".venv").resolve()
    if not venv_path.exists():
        run(["uv", "venv", "--python", args.python])

    run(["uv", "sync"])

    # 安装 PyInstaller（构建依赖）
    run(["uv", "pip", "install", "pyinstaller"])

    # 清理
    if args.clean:
        for d in ["dist", "build"]:
            p = Path(d)
            if p.exists():
                shutil.rmtree(p)
                print(f"已清理: {d}/")

    # 构建命令（优先用 venv 里的 pyinstaller.exe，裸 uv 环境的子进程 PATH 里没有它）
    venv_pyinstaller = venv_path / "Scripts" / "pyinstaller.exe"
    pyinstaller_cmd = str(venv_pyinstaller) if venv_pyinstaller.exists() else "pyinstaller"
    cmd = [
        pyinstaller_cmd,
        "--noconfirm",
        "--distpath", "dist",
        "--workpath", "build",
        "--clean",
        "scripts/agent_customer.spec",
    ]

    run(cmd)

    # 检查 PyInstaller 结果
    dist_dir = Path("dist") / "AgentCustomer"
    dist_exe = dist_dir / "AgentCustomer.exe"
    if not dist_exe.exists():
        raise RuntimeError("PyInstaller 构建失败，找不到 AgentCustomer.exe")
    size = dist_exe.stat().st_size / (1024 * 1024)
    print(f"\nPyInstaller 构建成功: {dist_exe} ({size:.1f} MB)")

    # 打包成单个安装程序
    if args.skip_installer:
        print("已跳过安装程序打包（--skip-installer）")
        print(f"onedir 输出目录: {dist_dir.absolute()}")
        return

    installer_dir, version = build_installer()
    # 文件名带版本号，精确匹配，避免拿到旧版本的 setup.exe
    setup = installer_dir / f"Agent-Customer-Setup-{version}.exe"
    if not setup.exists():
        # 兜底：取目录里最新的 setup
        setups = sorted(installer_dir.glob("*.exe"), key=lambda p: p.stat().st_mtime)
        if not setups:
            raise RuntimeError("Inno Setup 编译完成但未找到 setup.exe")
        setup = setups[-1]
    ssize = setup.stat().st_size / (1024 * 1024)
    print(f"\n{'=' * 50}")
    print(f"发布包构建完成: {setup}")
    print(f"安装程序大小: {ssize:.1f} MB")
    print(f"{'=' * 50}")
    print("分发给用户的文件即此 setup.exe（双击安装，免管理员）")

if __name__ == "__main__":
    main()
