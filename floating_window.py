"""常驻置顶的悬浮窗：用进度条显示 5h / 7天 用量占比 + 绝对 token 量。

- 进度条 = 已用 token / 配置限额（限额在设置里按自己经验填）
- 可拖动，位置记忆到 config
- 右键菜单：刷新 / 设置 / 置顶开关 / 开机自启 / 退出
- 双击打开设置
- 自带后台 fetcher + 定时刷新
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from PyQt5.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QAction, QApplication, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QMenu, QMessageBox, QProgressBar, QVBoxLayout, QWidget,
)

import autostart
from config import AppConfig
from settings_dialog import SettingsDialog
from usage_fetcher import UsageFetcher, UsageSnapshot


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(n)


def _fmt_remaining(td_seconds: float) -> str:
    if td_seconds <= 0:
        return "已到时"
    s = int(td_seconds)
    h, r = divmod(s, 3600)
    m, _ = divmod(r, 60)
    if h > 0:
        return f"{h}h{m}m"
    return f"{m}m"


def _bar_gradient(pct: float) -> tuple[str, str, str]:
    """按占比返回 (亮色, 暗色, 文字色)，用于渐变进度条与百分比文字。"""
    if pct >= 90:
        return ("#ff7a6e", "#e0504a", "#ff8c80")   # 红
    if pct >= 70:
        return ("#ffc861", "#e0a52f", "#ffcf72")   # 黄
    return ("#5fb0ff", "#2d6cdb", "#7dc0ff")       # 蓝


class FloatingWindow(QWidget):
    request_quit = pyqtSignal()

    def __init__(self, cfg: AppConfig, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.last_snapshot: Optional[UsageSnapshot] = None
        self._fetcher: Optional[UsageFetcher] = None
        self._drag_offset: Optional[QPoint] = None

        self._build_ui()
        self._apply_window_flags()
        self._apply_opacity()
        self._restore_position()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_now)
        self._apply_interval()
        QTimer.singleShot(100, self.refresh_now)

    # ---------- UI ----------

    def _build_ui(self) -> None:
        self.setObjectName("floatRoot")
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.card = QWidget(self)
        self.card.setObjectName("card")
        self.card.setFixedWidth(158)
        outer.addWidget(self.card)
        self._refresh_style()

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(22)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 3)
        self.card.setGraphicsEffect(shadow)

        v = QVBoxLayout(self.card)
        v.setContentsMargins(11, 8, 11, 8)
        v.setSpacing(4)

        # 品牌行：圆点 + Claude + 右侧更新时间
        brand_row = QHBoxLayout()
        brand_row.setSpacing(5)
        self.dot = QLabel("●")
        self.dot.setStyleSheet("color:#5fb0ff; font-size:9px;")
        brand_row.addWidget(self.dot)
        lbl_brand = QLabel("Claude")
        lbl_brand.setStyleSheet(
            "color:#dfe6f0; font-size:10px; font-weight:bold;"
            " letter-spacing:1px;")
        brand_row.addWidget(lbl_brand)
        brand_row.addStretch(1)
        self.lbl_foot = QLabel("…")
        self.lbl_foot.setStyleSheet("color:#7a8699; font-size:8px;")
        brand_row.addWidget(self.lbl_foot)
        v.addLayout(brand_row)

        # 5h 行
        self.bar_5h, self.cap_5h, self.meta_5h = self._make_row(v, "5h")
        # 周 行
        self.bar_wk, self.cap_wk, self.meta_wk = self._make_row(v, "周")

    def _make_row(self, parent_layout, tag_text):
        """一行 = [标签 进度条 占比%] + 下方 meta。返回 (bar, caption, meta)。"""
        top = QHBoxLayout()
        top.setSpacing(7)
        tag = QLabel(tag_text)
        tag.setStyleSheet("color:#aab4c2; font-size:9px; font-weight:bold;")
        tag.setFixedWidth(16)
        top.addWidget(tag)

        bar = QProgressBar()
        bar.setRange(0, 1000)          # 千分比提精度
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        top.addWidget(bar, 1)

        caption = QLabel("—")
        caption.setStyleSheet("color:#eef2f8; font-size:12px; font-weight:bold;")
        caption.setFixedWidth(34)
        top.addWidget(caption, 0, Qt.AlignRight | Qt.AlignVCenter)
        parent_layout.addLayout(top)

        meta = QLabel("")
        meta.setStyleSheet("color:#8b97a8; font-size:8px; padding-left:23px;")
        parent_layout.addWidget(meta)
        return bar, caption, meta

    def _style_bar(self, bar: QProgressBar, pct: float) -> None:
        light, dark, _ = _bar_gradient(pct)
        bar.setValue(int(max(0.0, min(100.0, pct)) * 10))
        bar.setStyleSheet(
            "QProgressBar { background:rgba(255,255,255,28); border:none;"
            " border-radius:3px; }"
            "QProgressBar::chunk {"
            " background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            " stop:0 %s, stop:1 %s); border-radius:3px; }" % (dark, light)
        )

    def _refresh_style(self) -> None:
        # 卡片用近不透明渐变；整体透明度交给 setWindowOpacity 调节
        css = (
            "#card {"
            " background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            " stop:0 rgba(42,49,66,250), stop:1 rgba(26,31,44,250));"
            " border:1px solid rgba(120,140,175,90);"
            " border-radius:12px; }"
        )
        self.card.setStyleSheet(css)

    def _apply_opacity(self) -> None:
        self.setWindowOpacity(max(40, min(100, self.cfg.opacity)) / 100.0)

    def _style_caption(self, label, pct: float) -> None:
        _, _, txt = _bar_gradient(pct)
        label.setStyleSheet(
            "color:%s; font-size:12px; font-weight:bold;" % txt
        )

    def _apply_window_flags(self) -> None:
        flags = Qt.FramelessWindowHint | Qt.Tool
        if self.cfg.always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def _restore_position(self) -> None:
        self.adjustSize()
        self._auto_pos = not (self.cfg.pos_x >= 0 and self.cfg.pos_y >= 0)
        if self._auto_pos:
            self._anchor_bottom_right()
        else:
            self.move(self.cfg.pos_x, self.cfg.pos_y)

    def _anchor_bottom_right(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 20,
                  screen.bottom() - self.height() - 20)

    def _clamp_to_screen(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        x = min(self.x(), screen.right() - self.width() - 4)
        y = min(self.y(), screen.bottom() - self.height() - 4)
        x = max(x, screen.left() + 4)
        y = max(y, screen.top() + 4)
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    # ---------- 拖动 ----------

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_offset = e.globalPos() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self._drag_offset)
            e.accept()

    def mouseReleaseEvent(self, e):
        if self._drag_offset is not None:
            self._drag_offset = None
            self._auto_pos = False
            self.cfg.pos_x = self.x()
            self.cfg.pos_y = self.y()
            self._save_cfg_quiet()
            e.accept()

    def mouseDoubleClickEvent(self, e):
        self.show_settings()
        e.accept()

    # ---------- 右键菜单 ----------

    def contextMenuEvent(self, e):
        m = QMenu(self)
        m.addAction("立即刷新", self.refresh_now)
        m.addAction("设置…", self.show_settings)
        m.addSeparator()
        a_top = QAction("窗口置顶", m, checkable=True)
        a_top.setChecked(self.cfg.always_on_top)
        a_top.toggled.connect(self._toggle_on_top)
        m.addAction(a_top)
        a_auto = QAction("开机自启", m, checkable=True)
        a_auto.setChecked(self.cfg.autostart)
        a_auto.toggled.connect(self._toggle_autostart)
        m.addAction(a_auto)
        m.addSeparator()
        m.addAction("退出", self.request_quit.emit)
        m.exec_(e.globalPos())

    # ---------- 行为 ----------

    def _apply_interval(self) -> None:
        self._timer.start(max(1000, self.cfg.refresh_seconds * 1000))

    def refresh_now(self) -> None:
        if self._fetcher is not None and self._fetcher.isRunning():
            return
        self._fetcher = UsageFetcher(
            self.cfg.ccusage_cmd,
            weekly_reset_weekday=self.cfg.weekly_reset_weekday,
            weekly_reset_hour=self.cfg.weekly_reset_hour,
            manual_5h_default=self.cfg.limit_5h_cost,
            manual_week_default=self.cfg.limit_week_cost,
            parent=self,
        )
        self._fetcher.snapshot_ready.connect(self._on_snapshot)
        self._fetcher.start()

    def _preview_opacity(self, v: int) -> None:
        self.setWindowOpacity(max(40, min(100, v)) / 100.0)

    def show_settings(self) -> None:
        ok = self.last_snapshot is not None and self.last_snapshot.error is None
        dlg = SettingsDialog(self.cfg, ok, parent=self,
                             on_opacity_preview=self._preview_opacity)
        if dlg.exec_():
            new_cfg = dlg.to_config()
            new_cfg.pos_x = self.cfg.pos_x
            new_cfg.pos_y = self.cfg.pos_y
            new_cfg.always_on_top = self.cfg.always_on_top
            try:
                new_cfg.save()
            except OSError as ex:
                QMessageBox.warning(self, "保存失败", f"无法写入配置：{ex}")
                return
            old_interval = self.cfg.refresh_seconds
            self.cfg = new_cfg
            if new_cfg.refresh_seconds != old_interval:
                self._apply_interval()
            self._apply_opacity()
            autostart.sync(new_cfg.autostart)
            if self.last_snapshot:
                self._render(self.last_snapshot)
            self.refresh_now()
        else:
            self._apply_opacity()  # 取消则恢复

    def _toggle_on_top(self, checked: bool) -> None:
        self.cfg.always_on_top = checked
        self._apply_window_flags()
        self.show()
        self._save_cfg_quiet()

    def _toggle_autostart(self, checked: bool) -> None:
        try:
            autostart.sync(checked)
        except OSError as e:
            QMessageBox.warning(self, "开机自启失败", str(e))
            return
        self.cfg.autostart = checked
        self._save_cfg_quiet()

    def _save_cfg_quiet(self) -> None:
        try:
            self.cfg.save()
        except OSError:
            pass

    # ---------- 数据 ----------

    def _on_snapshot(self, snap: UsageSnapshot) -> None:
        self.last_snapshot = snap
        self._render(snap)
        self.adjustSize()
        if getattr(self, "_auto_pos", False):
            self._anchor_bottom_right()
        else:
            self._clamp_to_screen()

    def _render(self, snap: UsageSnapshot) -> None:
        if snap.error:
            self.cap_5h.setText("⚠")
            self._style_bar(self.bar_5h, 0)
            self.meta_5h.setText("采集失败")
            self.cap_wk.setText("")
            self._style_bar(self.bar_wk, 0)
            self.meta_wk.setText("")
            self.lbl_foot.setText("右键→设置")
            self.setToolTip(snap.error)
            return

        now = datetime.now().astimezone()
        # 选择限额：auto_calibrate=True 且自适应有结果就用自适应，否则用手动
        if self.cfg.auto_calibrate and snap.auto_limit_5h > 0:
            lim5 = snap.auto_limit_5h
            lim5_src = "auto"
        else:
            lim5 = max(0.01, self.cfg.limit_5h_cost)
            lim5_src = "manual"
        if self.cfg.auto_calibrate and snap.auto_limit_week > 0:
            limw = snap.auto_limit_week
            limw_src = "auto"
        else:
            limw = max(0.01, self.cfg.limit_week_cost)
            limw_src = "manual"
        pct5 = snap.five_hour_cost * 100.0 / lim5
        pctw = snap.weekly_cost * 100.0 / limw
        self._last_lim5 = (lim5, lim5_src, snap.auto_limit_5h_source)
        self._last_limw = (limw, limw_src, snap.auto_limit_week_source)

        # 5h
        self._style_bar(self.bar_5h, pct5)
        self._style_caption(self.cap_5h, pct5)
        self.cap_5h.setText(f"{min(pct5,999):.0f}%")
        if snap.five_hour_end and snap.five_hour_active:
            end_local = snap.five_hour_end.astimezone()
            remain = (end_local - now).total_seconds()
            self.meta_5h.setText(f"剩 {_fmt_remaining(remain)}")
        else:
            self.meta_5h.setText("空闲")

        # 周
        self._style_bar(self.bar_wk, pctw)
        self._style_caption(self.cap_wk, pctw)
        self.cap_wk.setText(f"{min(pctw,999):.0f}%")
        if snap.weekly_reset_at:
            remain = (snap.weekly_reset_at - now).total_seconds()
            self.meta_wk.setText(f"{_fmt_remaining(remain)}后重置")
        else:
            self.meta_wk.setText("")

        self.lbl_foot.setText(f"{snap.fetched_at:%H:%M} 更新")

        # 完整信息放 tooltip
        mode_tag_5h = "auto" if lim5_src == "auto" else "手动"
        mode_tag_wk = "auto" if limw_src == "auto" else "手动"
        tip = [
            f"5h : ${snap.five_hour_cost:.2f} / ${lim5:.2f}  ({pct5:.0f}%)  [{mode_tag_5h}]",
        ]
        if lim5_src == "auto" and snap.auto_limit_5h_source:
            tip.append(f"     限额来源: {snap.auto_limit_5h_source}")
        if snap.five_hour_end and snap.five_hour_active:
            tip.append(f"     重置 {snap.five_hour_end.astimezone():%H:%M}")
        tip.append(f"周  : ${snap.weekly_cost:.2f} / ${limw:.2f}  ({pctw:.0f}%)  [{mode_tag_wk}]")
        if limw_src == "auto" and snap.auto_limit_week_source:
            tip.append(f"     限额来源: {snap.auto_limit_week_source}")
        if snap.weekly_reset_at:
            tip.append(f"     下次重置 {snap.weekly_reset_at:%m-%d %H:%M}")
        tip.append(f"更新 {snap.fetched_at:%H:%M:%S}")
        self.setToolTip("\n".join(tip))
