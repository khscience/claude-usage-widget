"""数据采集：subprocess 调 ccusage，解析 JSON。

周窗口与官方 /usage 一致：按"上次周重置时刻"为起点累加，而非滚动 7 天。
重置 weekday/hour 在配置里指定（默认周三 19:00）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from PyQt5.QtCore import QThread, pyqtSignal


def _resolve_executable(name: str) -> str:
    """Windows 上 `npx`/`ccusage` 等通常是 `.cmd` 包装脚本。
    subprocess 不通过 shell 不会找 `.cmd`/`.bat`，需自己解析。
    """
    if os.path.isabs(name) and os.path.exists(name):
        return name
    found = shutil.which(name)
    if found:
        return found
    if sys.platform == "win32":
        for ext in (".cmd", ".bat", ".exe"):
            found = shutil.which(name + ext)
            if found:
                return found
    return name  # 留给 subprocess 自己报 FileNotFoundError


@dataclass
class UsageSnapshot:
    # 5h 活跃块（来自 ccusage blocks --active）
    five_hour_tokens: int = 0
    five_hour_start: Optional[datetime] = None
    five_hour_end: Optional[datetime] = None
    five_hour_active: bool = False
    five_hour_cost: float = 0.0
    burn_rate_tpm: float = 0.0
    # 周窗口（自上次周重置起累加）
    weekly_tokens: int = 0
    weekly_cost: float = 0.0
    weekly_window_start: Optional[datetime] = None  # 本周窗口起点(本地时区)
    weekly_reset_at: Optional[datetime] = None      # 下次重置时刻(本地时区)
    # 元信息
    fetched_at: datetime = None
    error: Optional[str] = None

    def __post_init__(self):
        if self.fetched_at is None:
            self.fetched_at = datetime.now().astimezone()


def _parse_iso(ts: str) -> datetime:
    """解析 ccusage 输出的 ISO8601（带 Z）字符串为 UTC datetime。"""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def last_reset_at(weekday: int, hour: int,
                  now: Optional[datetime] = None) -> datetime:
    """返回上一次「每周 weekday hour:00」重置时刻（本地时区）。

    weekday: Python 风格，Mon=0..Sun=6
    """
    if now is None:
        now = datetime.now().astimezone()
    # 今天的 hour 点
    today_at = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    days_back = (now.weekday() - weekday) % 7
    candidate = today_at - timedelta(days=days_back)
    if candidate > now:
        candidate -= timedelta(days=7)
    return candidate


class UsageFetcher(QThread):
    """后台线程跑 ccusage，不阻塞 UI。每次 start() 跑一遍后退出。"""

    snapshot_ready = pyqtSignal(object)  # UsageSnapshot

    TIMEOUT_SECONDS = 30

    def __init__(self, ccusage_cmd: list[str],
                 weekly_reset_weekday: int = 2,
                 weekly_reset_hour: int = 19,
                 parent=None):
        super().__init__(parent)
        self.ccusage_cmd = list(ccusage_cmd)
        self.weekly_reset_weekday = weekly_reset_weekday
        self.weekly_reset_hour = weekly_reset_hour

    def run(self) -> None:  # type: ignore[override]
        try:
            snap = self._fetch()
        except Exception as e:  # noqa: BLE001
            snap = UsageSnapshot(error=f"采集异常: {e}")
        self.snapshot_ready.emit(snap)

    # --- 私有 ---

    def _run_ccusage(self, extra_args: list[str]) -> dict:
        if not self.ccusage_cmd:
            raise RuntimeError("ccusage 命令为空")
        head = _resolve_executable(self.ccusage_cmd[0])
        cmd = [head, *self.ccusage_cmd[1:], *extra_args]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT_SECONDS,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                f"找不到 ccusage 命令 ({self.ccusage_cmd[0]})。"
                "请先安装 Node.js，再运行：npm i -g ccusage"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"ccusage 调用超时 (>{self.TIMEOUT_SECONDS}s)") from e

        if proc.returncode != 0:
            stderr_tail = (proc.stderr or "").strip().splitlines()[-3:]
            raise RuntimeError("ccusage 返回非零: " + " | ".join(stderr_tail))
        if not proc.stdout.strip():
            raise RuntimeError("ccusage 无输出")
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"ccusage 输出非 JSON: {e}") from e

    def _fetch(self) -> UsageSnapshot:
        snap = UsageSnapshot()

        # 1) 5h 活跃块
        blocks_json = self._run_ccusage(["blocks", "--json", "--active"])
        blocks = blocks_json.get("blocks", []) if isinstance(blocks_json, dict) else []
        if blocks:
            b = blocks[0]
            snap.five_hour_tokens = int(b.get("totalTokens", 0) or 0)
            snap.five_hour_active = bool(b.get("isActive", False))
            snap.five_hour_cost = float(b.get("costUSD", 0.0) or 0.0)
            burn = b.get("burnRate") or {}
            snap.burn_rate_tpm = float(burn.get("tokensPerMinute", 0.0) or 0.0)
            for ts_field, attr in (("startTime", "five_hour_start"),
                                   ("endTime", "five_hour_end")):
                ts = b.get(ts_field)
                if ts:
                    try:
                        setattr(snap, attr, _parse_iso(ts))
                    except ValueError:
                        pass

        # 2) 周窗口：从上次重置时刻起累加（与官方 /usage 同口径）
        reset = last_reset_at(self.weekly_reset_weekday, self.weekly_reset_hour)
        snap.weekly_window_start = reset
        snap.weekly_reset_at = reset + timedelta(days=7)

        daily_json = self._run_ccusage(["daily", "--json"])
        days = daily_json.get("daily", []) if isinstance(daily_json, dict) else []
        # 按天近似：包含重置当天（轻微 over-count 重置前那几小时，可接受）
        cutoff = reset.date()
        wt = 0; wc = 0.0
        for d in days:
            period = d.get("period")
            if not period:
                continue
            try:
                day = datetime.strptime(period, "%Y-%m-%d").date()
            except ValueError:
                continue
            if day < cutoff:
                continue
            wt += int(d.get("totalTokens", 0) or 0)
            wc += float(d.get("totalCost", 0.0) or 0.0)
        snap.weekly_tokens = wt
        snap.weekly_cost = wc
        return snap
