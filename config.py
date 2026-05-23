"""配置加载与保存。

配置路径：%APPDATA%\\ClaudeUsageWidget\\config.json
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, asdict, field
from pathlib import Path


def config_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "ClaudeUsageWidget" / "config.json"


@dataclass
class AppConfig:
    refresh_seconds: int = 10
    ccusage_cmd: list[str] = field(default_factory=lambda: ["npx", "-y", "ccusage"])
    autostart: bool = False
    pos_x: int = -1          # 悬浮窗位置；-1 表示首次启动自动定位
    pos_y: int = -1
    always_on_top: bool = True
    opacity: int = 92        # 窗口不透明度百分比 (40-100)
    # 自动校准：基于历史用量推断限额（默认开），关掉则用下方手动值
    auto_calibrate: bool = True
    # 进度条分母用「费用 USD」，比 token 更稳（自带 cache read 折扣）
    limit_5h_cost: float = 34.25         # 5h 费用限额（USD）
                                          # auto=False 时使用；auto=True 时作为历史不足兜底
    limit_week_cost: float = 330.61      # 周费用限额（USD），同上
    # 周窗口重置：与官方 /usage 一致（默认周三 19:00；Mon=0..Sun=6）
    weekly_reset_weekday: int = 2
    weekly_reset_hour: int = 19

    @classmethod
    def load(cls) -> "AppConfig":
        path = config_path()
        if not path.exists():
            return cls()
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return cls()
        defaults = asdict(cls())
        defaults.update({k: v for k, v in data.items() if k in defaults})
        return cls(**defaults)

    def save(self) -> None:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(self), ensure_ascii=False, indent=2)
        # 原子写入：临时文件 + os.replace
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
