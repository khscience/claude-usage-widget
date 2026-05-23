# Claude Usage Floating Widget

**English** · [中文](README.md)

A Windows desktop **always-on-top floating widget** that shows real-time progress bars for Claude Code's **5-hour** and **7-day** rolling usage windows, auto-refreshing every N seconds. **Self-calibrating limits**, adjustable transparency, draggable, doesn't clutter the taskbar.

```
● Claude              23:45 updated
5h   ▓▓▓▓▓░░░   50%
     4h13m left
7d   ▓░░░░░░░   12%
     resets in 8h13m
```

---

## Quick Start (Recommended, No Python Needed)

### 1. Download the exe

Head to **[Releases](https://github.com/khscience/claude-usage-widget/releases/latest)** and download `ClaudeUsageWidget.exe` (single file, ~36 MB, double-click to run).

### 2. Install the data source (required)

The exe **does not bundle** the data source. You need **Node.js** and **ccusage** first:

```powershell
# 1) Install Node.js: https://nodejs.org (any LTS)
# 2) Install ccusage:
npm install -g ccusage
```

> Without these, the widget will show ⚠ collection failed.

### 3. Run

Double-click `ClaudeUsageWidget.exe`. The floating widget appears at the bottom-right of your screen.

- **Left-drag** the widget to move it; position is remembered
- **Right-click** for menu (Refresh / Settings / Always-on-top / Run at startup / Quit)
- **Double-click** to open Settings
- For auto-launch on boot: right-click → "Run at startup"

---

## How to Read It

- Progress bar = ccusage-computed **cost used** ÷ limit; colored by ratio (blue <70% / yellow <90% / red ≥90%)
- Hover for tooltip with full cost, limit source (`[auto]`/`[manual]`), and reset times
- 5h shows the current active block; "idle" if no recent activity
- The weekly window matches official `/usage`: **resets at the fixed weekday/hour you specify** (default Wed 19:00)

## Limit Calibration (Auto vs Manual)

Two modes — **auto by default**:

### Auto mode (recommended)

Infers real limits from **your own historical usage**, no manual tuning:

- **5h limit** = scan historical 5h blocks for the "**stopped early + resumed right at window reset**" pattern (signs of hitting the cap) → **median cost** of those blocks
- **Weekly limit** = group daily data into complete weeks by your reset weekday → **P95** of completed weekly totals
- Falls back to manual defaults when signals are insufficient (<2 cap-hits or <5 complete weeks of history)

### Manual mode

Open Claude Code, type `/usage` to see the official percentages, then compute **current cost ÷ official percentage** to derive the real limit and fill it into Settings:

- 5h limit = current 5h cost ÷ 5h percentage
- Weekly limit = current weekly cost ÷ weekly percentage

## Settings

| Field | Notes |
|---|---|
| Refresh interval | 5–3600 seconds, default 10 |
| Opacity | 40%–100% slider, live preview |
| **Limit mode** | **Auto-calibrate** (recommended) / Manual |
| 5h cost limit | Manual-mode denominator (USD), default $34.25; also serves as auto-mode fallback |
| Weekly cost limit | Same as above, default $330.61 |
| Weekly reset | Match what your `/usage` shows under "Resets …" (default Wed 19:00) |
| ccusage command | Default `npx -y ccusage`; if globally installed, just `ccusage` |
| Run at startup | Writes `HKCU\...\Run`, no admin needed |

> **Why cost instead of tokens?** ccusage's `totalTokens` counts cache reads at full weight (in practice cache reads are ~97% of the total), while Anthropic's rate limit weighs cache reads much lower. A token-based percentage would drift badly. Cost is naturally weighted by real pricing (cache reads are 0.1×), so it's far more stable.

Config file path: `%APPDATA%\ClaudeUsageWidget\config.json`

---

## Run From Source (Developers)

```powershell
git clone https://github.com/khscience/claude-usage-widget.git
cd claude-usage-widget
pip install -r requirements.txt
python main.py
```

### Repackage exe

```powershell
pip install pyinstaller pillow   # first time
build.bat                        # or run the line below manually
python -m PyInstaller --noconfirm --onefile --noconsole --name ClaudeUsageWidget --icon app.ico --add-data "app.ico;." main.py
```

## How It Works

There's no official programmatic API for Claude Code's `/usage` data. The desktop app doesn't fire statusLine (tested), and no local cache holds rate-limit percentages. So this tool uses the community-maintained [ccusage](https://github.com/ryoppippi/ccusage) CLI to parse local session files (`~/.claude/projects/**/*.jsonl`) for token usage stats.

```
[QTimer every N sec] → [QThread runs npx ccusage --json]
                         ├→ parse active 5h block + history
                         ├→ self-calibrate real limits (auto_limit.py)
                         └→ update progress bars + tooltip
```

## FAQ

**Q: Widget shows ⚠ / collection failed?**
A: ccusage call failed. Hover for the exact error. Common causes: Node.js not installed / ccusage not installed / wrong path. On Windows `npx` is actually `npx.cmd`; this tool auto-resolves `.cmd`/`.bat` suffixes.

**Q: 5h shows "idle"?**
A: No Claude Code activity in the current 5-hour window. Once you send a message in Claude Code, the next refresh will show usage and reset time.

**Q: Can't find the widget / dragged off-screen?**
A: Edit `%APPDATA%\ClaudeUsageWidget\config.json`, set `pos_x` and `pos_y` both to `-1`. On restart it returns to the bottom-right corner.

**Q: Is auto-mode's limit accurate?**
A: Depends on your history. With ≥2 cap-hit signals it's quite accurate; otherwise falls back to P95; otherwise to manual defaults. The tooltip shows the limit source so you can judge.

**Q: Why doesn't the percentage match `/usage` in Claude Code?**
A: This is a **local estimation** and won't match official numbers exactly. Auto mode infers from your historical cap-hit behavior; manual mode relies on your own calibration. Neither will be pixel-perfect, but both track the trend.

## License

MIT
