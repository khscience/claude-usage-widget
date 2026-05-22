"""通过 HKCU\\...\\Run 实现开机自启（无需管理员权限）。"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
ENTRY_NAME = "ClaudeUsageWidget"


def _launch_command() -> str:
    """返回开机时要执行的命令。

    - 打包成 exe（sys.frozen）时直接用 exe 自身路径。
    - 源码运行时优先用 pythonw.exe 避免黑色控制台窗口闪现。
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    py = Path(sys.executable)
    if py.name.lower() == "python.exe":
        pyw = py.with_name("pythonw.exe")
        if pyw.exists():
            py = pyw
    main_py = Path(__file__).resolve().parent / "main.py"
    return f'"{py}" "{main_py}"'


def is_enabled() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            winreg.QueryValueEx(k, ENTRY_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def enable() -> None:
    if winreg is None:
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, ENTRY_NAME, 0, winreg.REG_SZ, _launch_command())


def disable() -> None:
    if winreg is None:
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, ENTRY_NAME)
    except FileNotFoundError:
        pass


def sync(enabled: bool) -> None:
    if enabled:
        enable()
    else:
        disable()
