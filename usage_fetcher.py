"""数据采集：subprocess 调 ccusage，解析 JSON。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    five_hour_tokens: int = 0
    five_hour_start: Optional[datetime] = None  # UTC，5h 窗口开始时间
    five_hour_end: Optional[datetime] = None    # UTC，5h 窗口结束时间
    five_hour_active: bool = False              # 当前是否有活跃 5h 块
    five_hour_cost: float = 0.0                 # 本 5h 块花费 (USD)
    burn_rate_tpm: float = 0.0                  # 燃烧速率 tokens/min
    weekly_tokens: int = 0
    weekly_cost: float = 0.0                    # 7天窗口花费 (USD)
    weekly_oldest: Optional[datetime] = None    # 7天窗口里最早一条记录的日期（UTC 当天 00:00）
    fetched_at: datetime = None                 # 本快照生成时刻（本地时区）
    error: Optional[str] = None                 # 非 None 表示采集失败

    def __post_init__(self):
        if self.fetched_at is None:
            self.fetched_at = datetime.now().astimezone()


def _parse_iso(ts: str) -> datetime:
    """解析 ccusage 输出的 ISO8601（带 Z）字符串为 UTC datetime。"""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


class UsageFetcher(QThread):
    """后台线程跑 ccusage，不阻塞 UI。每次 start() 跑一遍后退出。"""

    snapshot_ready = pyqtSignal(object)  # UsageSnapshot

    TIMEOUT_SECONDS = 30

    def __init__(self, ccusage_cmd: list[str], parent=None):
        super().__init__(parent)
        self.ccusage_cmd = list(ccusage_cmd)

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
                # Windows 上避免黑色控制台窗口闪现
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

        # 1) 5h 滚动窗口（活跃块）
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
        # 没有活跃块：保持默认 0 / None

        # 2) 7天滚动窗口：聚合 daily 数据
        daily_json = self._run_ccusage(["daily", "--json"])
        days = daily_json.get("daily", []) if isinstance(daily_json, dict) else []
        # 今天（本地日期，按 UTC 偏移粗略对齐 ccusage 的 period 字段）
        today_local = datetime.now().astimezone().date()
        cutoff = today_local - timedelta(days=6)  # 含今天共 7 天
        weekly_total = 0
        weekly_cost = 0.0
        oldest_date = None
        for d in days:
            period = d.get("period")
            if not period:
                continue
            try:
                day = datetime.strptime(period, "%Y-%m-%d").date()
            except ValueError:
                continue
            if day < cutoff or day > today_local:
                continue
            weekly_total += int(d.get("totalTokens", 0) or 0)
            weekly_cost += float(d.get("totalCost", 0.0) or 0.0)
            if oldest_date is None or day < oldest_date:
                oldest_date = day
        snap.weekly_tokens = weekly_total
        snap.weekly_cost = weekly_cost
        if oldest_date is not None:
            snap.weekly_oldest = datetime.combine(
                oldest_date, datetime.min.time(), tzinfo=timezone.utc
            )
        return snap
