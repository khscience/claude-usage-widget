"""入口：启动 QApplication，显示常驻置顶悬浮窗。"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许脚本直接运行：把所在目录加到 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from config import AppConfig
from floating_window import FloatingWindow


def main() -> int:
    # 高 DPI 感知：文字/尺寸在缩放屏上清晰，坐标可预测
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("ClaudeUsageWidget")

    cfg = AppConfig.load()
    win = FloatingWindow(cfg)
    win.request_quit.connect(app.quit)
    win.show()

    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
