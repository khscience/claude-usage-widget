"""设置对话框。"""
from __future__ import annotations

import shlex

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from config import AppConfig, TIER_PRESETS


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, ccusage_ok: bool, parent=None,
                 on_opacity_preview=None,
                 current_5h_cost: float = 0.0,
                 current_week_cost: float = 0.0):
        super().__init__(parent)
        self.setWindowTitle("Claude 用量小工具 — 设置")
        self.setMinimumWidth(460)
        self.cfg = cfg
        self._on_opacity_preview = on_opacity_preview
        self._cur_5h = current_5h_cost
        self._cur_wk = current_week_cost

        root = QVBoxLayout(self)

        if not ccusage_ok:
            banner = QLabel(
                "⚠ 当前 ccusage 不可用。请先安装 Node.js，然后在终端运行：\n"
                "    npm install -g ccusage"
            )
            banner.setStyleSheet(
                "background:#fff3cd; color:#664d03; border:1px solid #ffe69c;"
                "padding:8px; border-radius:4px;"
            )
            banner.setWordWrap(True)
            root.addWidget(banner)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.refresh_spin = QSpinBox()
        self.refresh_spin.setRange(5, 3600)
        self.refresh_spin.setSuffix(" 秒")
        self.refresh_spin.setValue(cfg.refresh_seconds)
        form.addRow("刷新间隔：", self.refresh_spin)

        # 透明度滑块（实时预览）
        op_row = QWidget()
        op_lay = QHBoxLayout(op_row)
        op_lay.setContentsMargins(0, 0, 0, 0)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(40, 100)
        self.opacity_slider.setValue(max(40, min(100, cfg.opacity)))
        self.opacity_val = QLabel(f"{self.opacity_slider.value()}%")
        self.opacity_val.setFixedWidth(40)
        self.opacity_slider.valueChanged.connect(self._on_opacity_slide)
        op_lay.addWidget(self.opacity_slider, 1)
        op_lay.addWidget(self.opacity_val)
        form.addRow("不透明度：", op_row)

        # 订阅档位选择：切换时自动填手动限额预设
        self.tier_combo = QComboBox()
        for name in TIER_PRESETS:
            self.tier_combo.addItem(name)
        idx = max(0, self.tier_combo.findText(cfg.subscription_tier))
        self.tier_combo.setCurrentIndex(idx)
        self.tier_combo.currentTextChanged.connect(self._on_tier_changed)
        form.addRow("订阅档位：", self.tier_combo)

        # 自动校准开关 - 默认开
        self.auto_chk = QCheckBox("自动校准（基于历史用量推断，推荐）")
        self.auto_chk.setChecked(cfg.auto_calibrate)
        self.auto_chk.toggled.connect(self._on_auto_toggled)
        form.addRow("限额模式：", self.auto_chk)

        # 限额改用「费用 USD」—— 比 token 更稳（cache read 已按真实定价折算）
        self.limit5_spin = QDoubleSpinBox()
        self.limit5_spin.setRange(0.01, 100000.0)
        self.limit5_spin.setDecimals(2)
        self.limit5_spin.setPrefix("$ ")
        self.limit5_spin.setValue(cfg.limit_5h_cost)
        form.addRow("5h 费用限额：", self.limit5_spin)

        self.limitw_spin = QDoubleSpinBox()
        self.limitw_spin.setRange(0.01, 1000000.0)
        self.limitw_spin.setDecimals(2)
        self.limitw_spin.setPrefix("$ ")
        self.limitw_spin.setValue(cfg.limit_week_cost)
        form.addRow("周费用限额：", self.limitw_spin)

        # 初始化时按 auto 状态启用/禁用手动限额输入
        self._on_auto_toggled(cfg.auto_calibrate)

        # === 按官方百分比一键校准 ===
        calib_row = QWidget()
        calib_lay = QHBoxLayout(calib_row)
        calib_lay.setContentsMargins(0, 0, 0, 0)
        calib_lay.setSpacing(4)
        self.calib_5h = QDoubleSpinBox()
        self.calib_5h.setRange(0.0, 100.0)
        self.calib_5h.setDecimals(0)
        self.calib_5h.setSuffix("% 5h")
        self.calib_5h.setSpecialValueText("─")
        self.calib_5h.setValue(0)
        self.calib_wk = QDoubleSpinBox()
        self.calib_wk.setRange(0.0, 100.0)
        self.calib_wk.setDecimals(0)
        self.calib_wk.setSuffix("% 周")
        self.calib_wk.setSpecialValueText("─")
        self.calib_wk.setValue(0)
        self.calib_btn = QPushButton("应用")
        self.calib_btn.clicked.connect(self._apply_calibration)
        if self._cur_5h <= 0 and self._cur_wk <= 0:
            self.calib_btn.setEnabled(False)
            self.calib_btn.setToolTip("等悬浮窗拉到一次数据再校准")
        else:
            self.calib_btn.setToolTip(
                f"按当前 5h ${self._cur_5h:.2f} / 周 ${self._cur_wk:.2f} 反推真实限额")
        calib_lay.addWidget(self.calib_5h)
        calib_lay.addWidget(self.calib_wk)
        calib_lay.addWidget(self.calib_btn)
        form.addRow("按 /usage 校准：", calib_row)

        self.calib_status = QLabel("")
        self.calib_status.setStyleSheet("color:#0a7a3e; font-size:11px;")
        self.calib_status.setWordWrap(True)
        form.addRow("", self.calib_status)

        # 周窗口重置（与官方 /usage 一致）
        reset_row = QWidget()
        reset_lay = QHBoxLayout(reset_row)
        reset_lay.setContentsMargins(0, 0, 0, 0)
        self.reset_wd = QComboBox()
        for i, name in enumerate(["周一", "周二", "周三", "周四", "周五", "周六", "周日"]):
            self.reset_wd.addItem(name, i)
        self.reset_wd.setCurrentIndex(max(0, min(6, cfg.weekly_reset_weekday)))
        self.reset_hr = QSpinBox()
        self.reset_hr.setRange(0, 23)
        self.reset_hr.setSuffix(" 时")
        self.reset_hr.setValue(max(0, min(23, cfg.weekly_reset_hour)))
        reset_lay.addWidget(self.reset_wd)
        reset_lay.addWidget(self.reset_hr)
        reset_lay.addStretch(1)
        form.addRow("周窗口重置：", reset_row)

        self.ccusage_edit = QLineEdit(" ".join(_quote_arg(a) for a in cfg.ccusage_cmd))
        self.ccusage_edit.setPlaceholderText("npx -y ccusage")
        form.addRow("ccusage 命令：", self.ccusage_edit)

        self.autostart_chk = QCheckBox("开机自动启动")
        self.autostart_chk.setChecked(cfg.autostart)
        form.addRow("", self.autostart_chk)

        root.addLayout(form)

        hint = QLabel(
            "* 进度条 = 已用费用 ÷ 限额。\n"
            "  自动模式：扫历史 5h 块找「提前停手 + 等到重置才再开」的撞限信号，\n"
            "  这些块的 cost 中位数 ≈ 真实限额；历史不足时回退到下面手动值。\n"
            "  周窗口同理：P95 of 完整周累计 cost。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666; font-size:11px;")
        root.addWidget(hint)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        root.addWidget(line)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self._on_reject)
        root.addWidget(btns)

    def _on_auto_toggled(self, on: bool) -> None:
        """自动校准开启时禁用手动限额输入（视觉灰化）"""
        self.limit5_spin.setEnabled(not on)
        self.limitw_spin.setEnabled(not on)

    def _on_tier_changed(self, name: str) -> None:
        """切换订阅档位 → 自动填入预设的手动限额（Custom 不动）"""
        preset = TIER_PRESETS.get(name)
        if not preset or name == "Custom":
            return
        l5, lw = preset
        if l5 > 0:
            self.limit5_spin.setValue(l5)
        if lw > 0:
            self.limitw_spin.setValue(lw)

    def _apply_calibration(self) -> None:
        """读「官方 5h%」「官方 周%」，按当前实测 cost 反推真实限额并填入。"""
        p5 = self.calib_5h.value()
        pw = self.calib_wk.value()
        applied = []
        if p5 > 0 and self._cur_5h > 0:
            new5 = self._cur_5h / (p5 / 100.0)
            self.limit5_spin.setValue(new5)
            applied.append(f"5h ${new5:.2f}")
        if pw > 0 and self._cur_wk > 0:
            neww = self._cur_wk / (pw / 100.0)
            self.limitw_spin.setValue(neww)
            applied.append(f"周 ${neww:.2f}")
        if not applied:
            self.calib_status.setStyleSheet("color:#a04040; font-size:11px;")
            self.calib_status.setText("⚠ 请至少填一个非 0 的百分比")
            return
        # 校准后切到 Custom + 关掉自适应（用户给了精确锚点）
        idx = self.tier_combo.findText("Custom")
        if idx >= 0:
            self.tier_combo.setCurrentIndex(idx)
        self.auto_chk.setChecked(False)
        self.calib_status.setStyleSheet("color:#0a7a3e; font-size:11px;")
        self.calib_status.setText(
            "✓ 已写入：" + " · ".join(applied) + "  （切到 Custom + 关闭自动校准）"
        )

    def _on_opacity_slide(self, v: int) -> None:
        self.opacity_val.setText(f"{v}%")
        if self._on_opacity_preview:
            self._on_opacity_preview(v)   # 实时预览

    def _on_reject(self) -> None:
        # 取消时恢复原不透明度
        if self._on_opacity_preview:
            self._on_opacity_preview(self.cfg.opacity)
        self.reject()

    def to_config(self) -> AppConfig:
        cmd_text = self.ccusage_edit.text().strip() or "npx -y ccusage"
        try:
            cmd = shlex.split(cmd_text, posix=False)
        except ValueError:
            cmd = cmd_text.split()
        return AppConfig(
            refresh_seconds=self.refresh_spin.value(),
            ccusage_cmd=cmd,
            autostart=self.autostart_chk.isChecked(),
            subscription_tier=self.tier_combo.currentText(),
            auto_calibrate=self.auto_chk.isChecked(),
            limit_5h_cost=float(self.limit5_spin.value()),
            limit_week_cost=float(self.limitw_spin.value()),
            weekly_reset_weekday=int(self.reset_wd.currentData()),
            weekly_reset_hour=int(self.reset_hr.value()),
            opacity=self.opacity_slider.value(),
        )


def _quote_arg(a: str) -> str:
    return f'"{a}"' if " " in a else a
