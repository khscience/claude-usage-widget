# Claude 用量悬浮窗小工具

Windows 桌面**常驻置顶悬浮窗**，用进度条实时显示 Claude Code 的 **5 小时** 与 **7 天**滚动窗口用量占比，每隔 N 秒自动刷新。半透明可调、可拖动、不占任务栏。

```
● Claude              23:45 更新
5h   ▓▓▓▓▓░░░   50%
     剩 4h13m
7d   ▓░░░░░░░   12%
     8h13m后回收
```

---

## 快速开始（推荐，无需 Python）

### 1. 下载 exe

到 **[Releases 页面](https://github.com/khscience/claude-usage-widget/releases/latest)** 下载 `ClaudeUsageWidget.exe`（单文件，约 36 MB，双击即用）。

### 2. 安装数据来源（必需）

exe **不含**数据源，运行前请先装好 **Node.js** 和 **ccusage**：

```powershell
# 1) 装 Node.js：https://nodejs.org （任意 LTS 版本）
# 2) 装 ccusage：
npm install -g ccusage
```

> 没装的话，悬浮窗会显示 ⚠ 采集失败。

### 3. 运行

双击 `ClaudeUsageWidget.exe`，桌面右下角即出现悬浮窗。

- **左键拖动**：移动窗口，位置自动记忆
- **右键**：菜单（立即刷新 / 设置 / 窗口置顶 / 开机自启 / 退出）
- **双击**：打开设置
- 想开机自动启动：右键勾选「开机自启」

---

## 界面说明

- 进度条 = 本地估算已用 token ÷ 你设定的限额；颜色随占比变（蓝 <70% / 黄 <90% / 红 ≥90%）
- 鼠标悬停看 tooltip（完整 token 数、费用、重置时刻）
- 5h 窗口空闲（无活动）时显示「空闲」

## 设置

| 字段 | 说明 |
|---|---|
| 刷新间隔 | 5–3600 秒，默认 10 |
| 不透明度 | 40%–100% 滑块，实时预览 |
| 5h 进度条限额 | 进度条分母（百万 token 为单位），按经验调 |
| 7天 进度条限额 | 进度条分母（百万 token 为单位），按经验调 |
| ccusage 命令 | 默认 `npx -y ccusage`；装了全局版可填 `ccusage` |
| 开机自动启动 | 写 `HKCU\...\Run`，无需管理员权限 |

> **关于限额校准**：Anthropic 没公开精确 token 配额，且 ccusage 把 cache read 全额计入，与官方 `/usage` 百分比口径不同。所以默认限额只是「让进度条有个分母」。**校准方法**：打开 Claude Code 输入 `/usage` 看到官方百分比，用「当前 token ÷ 官方百分比」反推限额填进设置，进度条就准了。

配置文件路径：`%APPDATA%\ClaudeUsageWidget\config.json`

---

## 从源码运行（开发者）

```powershell
git clone https://github.com/khscience/claude-usage-widget.git
cd claude-usage-widget
pip install -r requirements.txt
python main.py
```

### 重新打包 exe

```powershell
pip install pyinstaller pillow   # 首次
build.bat                        # 或手动执行下面这行
python -m PyInstaller --noconfirm --onefile --noconsole --name ClaudeUsageWidget --icon app.ico --add-data "app.ico;." main.py
```

## 工作原理

Claude Code 官方没有 `/usage` 数据的程序化接口，桌面端也不渲染 statusLine（已实测）、本地缓存里也不存限流百分比。所以本工具通过社区维护的 [ccusage](https://github.com/ryoppippi/ccusage) CLI 读取本地会话文件（`~/.claude/projects/**/*.jsonl`）来统计 token 用量。

```
[QTimer 每 N 秒] → [QThread 跑 npx ccusage --json] → [解析 JSON] → [更新进度条 + tooltip]
```

## 常见问题

**Q：悬浮窗显示 ⚠ / 采集失败？**
A：ccusage 调用失败。鼠标悬停看具体错误。常见原因：未装 Node.js / 未装 ccusage / 路径不对。Windows 上 `npx` 实为 `npx.cmd`，本工具已自动解析 `.cmd`/`.bat` 后缀。

**Q：5h 显示「空闲」？**
A：当前 5 小时窗口内没有任何 Claude Code 活动。一旦你用 Claude Code 发消息，下次刷新就会显示占比和重置时间。

**Q：窗口找不到了 / 拖出屏幕了？**
A：编辑 `%APPDATA%\ClaudeUsageWidget\config.json`，把 `pos_x`、`pos_y` 都改成 `-1`，重启后会自动回到右下角。

**Q：进度条占比和 Claude Code 里 `/usage` 不一致？**
A：这是**本地估算**，且 ccusage 与官方口径不同。按上文「关于限额校准」调一次限额即可对齐。
