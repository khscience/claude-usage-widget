"""自动校准限额：基于历史用量推断 5h / 7天 真实限额。

算法（双信号 hybrid）：
==============================
5h 限额：
  Signal B (强): 历史 block 提前停手 + 下一块恰好等到 5h 窗口重置 → 撞限
                 这些 block 的 cost 中位数 ≈ 真实限额
  Signal D (弱兜底): P95 of 所有已完成 block cost
                     —— 假设你历史上偶尔会推到上限附近

7天限额：
  按用户配置的「周重置时刻」把历史每日数据切成完整周
  P95 / Max of 完整周累计 cost
==============================

任何阶段：算出值 < min_default 一律回退默认。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Iterable, Optional


def _parse_iso(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _percentile(sorted_values: list[float], p: float) -> float:
    """简单 P-th percentile（0..1），输入需已排序。"""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = int(round(p * (len(sorted_values) - 1)))
    return sorted_values[idx]


# ============================================================
# 5 小时窗口
# ============================================================

# 撞限信号判定阈值
_MIN_COST_FOR_HIT = 5.0          # 撞限块至少花了多少 USD（过滤"试一下"的小块）
_MIN_EARLY_STOP_SEC = 30 * 60    # actualEndTime 距 endTime 至少早多少（30 分钟）
_MAX_NEXT_GAP_SEC = 20 * 60      # 下一非 gap 块的 startTime 距 endTime 容差


def estimate_5h_limit(
    blocks: list[dict],
    min_default: float = 34.25,
) -> tuple[float, str]:
    """从 ccusage `blocks --json` 推断 5h 真实限额。

    Args:
        blocks: ccusage blocks 输出里的 "blocks" 列表
        min_default: 历史不足时的兜底默认值

    Returns:
        (estimated_limit_USD, source_explanation)
    """
    completed = [
        b for b in blocks
        if not b.get("isGap") and not b.get("isActive")
        and b.get("costUSD", 0) > 0.01
        and b.get("startTime") and b.get("endTime") and b.get("actualEndTime")
    ]
    if len(completed) < 3:
        return (min_default, f"历史块不足({len(completed)})，用默认")

    completed.sort(key=lambda b: b["startTime"])

    # ---- Signal B: 撞限检测 ----
    hit_costs: list[float] = []
    for i, b in enumerate(completed):
        try:
            cost = float(b["costUSD"])
            if cost < _MIN_COST_FOR_HIT:
                continue
            end = _parse_iso(b["endTime"])
            actual_end = _parse_iso(b["actualEndTime"])
            if (end - actual_end).total_seconds() < _MIN_EARLY_STOP_SEC:
                continue  # 没明显早停，可能是自然结束
            # 找下一个非 gap 真实块
            next_start: Optional[datetime] = None
            for nb in completed[i + 1:]:
                next_start = _parse_iso(nb["startTime"])
                break
            if next_start is None:
                continue
            diff = abs((next_start - end).total_seconds())
            if diff <= _MAX_NEXT_GAP_SEC:
                # 下一块紧贴 5h 窗口重置 → 强烈撞限信号
                hit_costs.append(cost)
        except (ValueError, KeyError, TypeError):
            continue

    if len(hit_costs) >= 2:
        est = median(hit_costs)
        # 强信号：直接使用，不被 min_default 压住
        return (est, f"基于 {len(hit_costs)} 次撞限信号 (中位数 ${est:.2f})")

    # ---- Signal D: P95 兜底 ----
    costs = sorted(float(b["costUSD"]) for b in completed)
    if len(costs) >= 10:
        est = _percentile(costs, 0.95)
        tag = f"P95 of {len(costs)} 块"
    else:
        est = costs[-1]
        tag = f"Max of {len(costs)} 块"
    if est < min_default:
        return (min_default, f"{tag} 低于默认，沿用默认")
    return (est, f"{tag} (${est:.2f})")


# ============================================================
# 7 天窗口
# ============================================================

def _week_anchor(d: date, reset_weekday: int) -> date:
    """给一个日期，返回它所属的周窗口的起点日期。"""
    days_back = (d.weekday() - reset_weekday) % 7
    return d - timedelta(days=days_back)


def estimate_week_limit(
    daily: list[dict],
    weekly_reset_weekday: int,
    weekly_reset_hour: int,  # 仅参考，按日聚合，不细到小时
    min_default: float = 330.61,
) -> tuple[float, str]:
    """从 ccusage `daily --json` 按周分组后推断真实周限额。"""
    if not daily:
        return (min_default, "无日数据")

    # 按周窗口聚合
    today = datetime.now().astimezone().date()
    current_anchor = _week_anchor(today, weekly_reset_weekday)
    weekly_totals: dict[date, float] = {}
    for d in daily:
        period = d.get("period")
        if not period:
            continue
        try:
            day = datetime.strptime(period, "%Y-%m-%d").date()
        except ValueError:
            continue
        anchor = _week_anchor(day, weekly_reset_weekday)
        weekly_totals[anchor] = weekly_totals.get(anchor, 0.0) + float(d.get("totalCost", 0) or 0)

    # 排除当前不完整的周
    completed_weeks = [
        c for a, c in weekly_totals.items()
        if a != current_anchor and c > 1.0
    ]
    if len(completed_weeks) < 2:
        return (
            min_default,
            f"完整周不足({len(completed_weeks)})，用默认"
        )

    completed_weeks.sort()
    if len(completed_weeks) >= 5:
        # 周数据较多：信任 P95，不被 min_default 压住
        est = _percentile(completed_weeks, 0.95)
        return (est, f"P95 of {len(completed_weeks)} 周 (${est:.2f})")
    # 周数据少（2-4 周）：用 Max 但保留 min_default 兜底
    est = completed_weeks[-1]
    if est < min_default:
        return (min_default, f"Max of {len(completed_weeks)} 周低于默认，沿用")
    return (est, f"Max of {len(completed_weeks)} 周 (${est:.2f})")
