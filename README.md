# Claude 用量悬浮窗小工具

Windows 桌面**常驻置顶悬浮窗**，显示 Claude Code 的 **5 小时滚动窗口** 与 **7 天滚动窗口** 已用 **token 绝对量**，每隔 N 秒自动刷新，并显示 5h 窗口的重置时间。可拖动、记住位置、不占任务栏。

## 工作原理

Claude Code 官方没有 `/usage` 数据的程序化接口，桌面端也不渲染 statusLine（已实测）、本地缓存里也不存限流百分比。所以本工具通过社区维护的 [ccusage](https://github.com/ryoppippi/ccusage) CLI 读取本地会话文件（`~/.claude/projects/**/*.jsonl`）来统计 token 用量。

数据流：
```
[QTimer 每 N 秒] → [QThread 跑 npx ccusage --json] → [解析 JSON] → [QPainter 重绘托盘图标 + 更新 tooltip]
```

> **为什么是绝对 token 量、不是百分比？**
> ccusage 的 `totalTokens` 把 cache read 按全额计入，而 Anthropic 官方 `/usage` 的限流百分比给 cache read 的权重低得多。两者比例对不上（实测 5h 用了 41% 才 16M token，7 天才 4% 却有 234M token）。所以按 token 数硬算百分比会严重失真 —— 干脆只显示**诚实的绝对 token 量**。

## 前置依赖

1. **Python 3.10+**
2. **PyQt5**：`pip install -r requirements.txt`
3. **Node.js**（任意 LTS 版本）
4. **ccusage**：可全局安装 `npm install -g ccusage`，也可保留默认 `npx -y ccusage`（首次会自动拉取）

## 运行

```powershell
cd others\claude_usage_widget
pip install -r requirements.txt
python main.py
```

桌面右下角出现一个深色半透明悬浮窗，用进度条显示占比：

```
Claude 用量
5h          45%   17.9M/40.0M
[████████░░░░░░░░]
重置 04:00（剩 4h35m）
7天          30%   296.0M/1.00B
[█████░░░░░░░░░░░]
8h35m后回收
23:24 更新 · 7d≈$208
```

- 进度条 = 已用 token ÷ 你在设置里填的限额；颜色随占比变（蓝<70% / 黄<90% / 红≥90%）
- **左键拖动**：移动窗口，位置自动记忆
- **右键**：菜单（立即刷新 / 设置 / 窗口置顶 / 开机自启 / 退出）
- **双击**：直接打开设置
- 5h 窗口空闲（无活动）时显示「空闲」

## 设置

| 字段 | 说明 |
|---|---|
| 刷新间隔 | 5–3600 秒，默认 10 |
| 5h 进度条限额 | 进度条分母，默认 40M token，按经验调 |
| 7天 进度条限额 | 进度条分母，默认 1B token，按经验调 |
| ccusage 命令 | 默认 `npx -y ccusage`；装了全局版可填 `ccusage` |
| 开机自动启动 | 写 `HKCU\...\Run`，无需管理员权限 |

> **关于限额**：Anthropic 没公开精确的 token 配额，且 ccusage 把 cache read 全额计入，与官方 `/usage` 百分比口径不同。所以这里的限额是「让进度条有个分母」，请按自己实际触发限流时的体验微调，填得越准越接近真实占比。

配置文件路径：`%APPDATA%\ClaudeUsageWidget\config.json`

## 打包为 exe

已打包好：**`dist\ClaudeUsageWidget.exe`**（约 36 MB，单文件，双击即用，无需 Python 环境）。

> exe 仍然需要系统已装 **Node.js + ccusage**（数据来源），这两个不会被打包进去。

重新打包（改了代码后）：

```powershell
pip install pyinstaller pillow   # 首次
build.bat                        # 或手动执行下面这行
python -m PyInstaller --noconfirm --onefile --noconsole --name ClaudeUsageWidget --icon app.ico --add-data "app.ico;." main.py
```

勾选"开机自启"后下次开机自动加载（已适配 exe：注册表写的是 exe 自身路径）。

## 常见问题

**Q：悬浮窗显示 ⚠ / 采集失败？**
A：ccusage 调用失败。看窗口底部的错误。常见原因：未装 Node.js / 未装 ccusage / 路径不对。Windows 上 `npx` 实为 `npx.cmd`，本工具已自动解析 `.cmd`/`.bat` 后缀。

**Q：5h 显示「空闲」？**
A：当前 5 小时窗口内没有任何 Claude Code 活动。一旦你用 Claude Code 发消息，下次刷新就会显示 token 数和重置时间。

**Q：窗口找不到了 / 拖出屏幕了？**
A：编辑 `%APPDATA%\ClaudeUsageWidget\config.json`，把 `pos_x`、`pos_y` 都改成 `-1`，重启后会自动回到右下角。

**Q：数字和 Claude Code 里 `/usage` 不一致？**
A：这是**本地估算**，且只显示绝对 token 量，不是 `/usage` 的限流百分比。两者口径不同，不会一致 —— 详见上文「为什么是绝对 token 量」。

**Q：能不能显示成百分比 / 进度条？**
A：需要一个可信的"限额分母"。官方限额（按加权 token 算）拿不到，硬填一个数会失真。如果你愿意接受粗略估算，可以联系作者加一个"加权 token + 自定义限额"模式。
