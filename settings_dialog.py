"""设置对话框。"""
from __future__ import annotations

import shlex

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from config import AppConfig


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, ccusage_ok: bool, parent=None,
                 on_opacity_preview=None):
        super().__init__(parent)
        self.setWindowTitle("Claude 用量小工具 — 设置")
        self.setMinimumWidth(440)
        self.cfg = cfg
        self._on_opacity_preview = on_opacity_preview

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

        # 限额以「百万 token」为单位，避免 QSpinBox int 上限（~2.1B）问题
        self.limit5_spin = QDoubleSpinBox()
        self.limit5_spin.setRange(0.1, 100000.0)
        self.limit5_spin.setDecimals(1)
        self.limit5_spin.setSuffix(" M tok")
        self.limit5_spin.setValue(cfg.limit_5h_tokens / 1_000_000)
        form.addRow("5h 进度条限额：", self.limit5_spin)

        self.limitw_spin = QDoubleSpinBox()
        self.limitw_spin.setRange(0.1, 100000.0)
        self.limitw_spin.setDecimals(1)
        self.limitw_spin.setSuffix(" M tok")
        self.limitw_spin.setValue(cfg.limit_week_tokens / 1_000_000)
        form.addRow("7天 进度条限额：", self.limitw_spin)

        self.ccusage_edit = QLineEdit(" ".join(_quote_arg(a) for a in cfg.ccusage_cmd))
        self.ccusage_edit.setPlaceholderText("npx -y ccusage")
        form.addRow("ccusage 命令：", self.ccusage_edit)

        self.autostart_chk = QCheckBox("开机自动启动")
        self.autostart_chk.setChecked(cfg.autostart)
        form.addRow("", self.autostart_chk)

        root.addLayout(form)

        hint = QLabel(
            "* 进度条 = 本地估算已用 token ÷ 上面的限额。\n"
            "  限额无官方精确值，请按自己触发限流时的经验填，\n"
            "  填得越准，进度条越接近真实占比。"
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
            limit_5h_tokens=int(self.limit5_spin.value() * 1_000_000),
            limit_week_tokens=int(self.limitw_spin.value() * 1_000_000),
            opacity=self.opacity_slider.value(),
        )


def _quote_arg(a: str) -> str:
    return f'"{a}"' if " " in a else a
