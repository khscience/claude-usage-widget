@echo off
REM 打包 Claude 用量悬浮窗为单文件 exe
REM 需先: pip install pyinstaller pillow
cd /d "%~dp0"
python -m PyInstaller --noconfirm --onefile --noconsole ^
  --name ClaudeUsageWidget ^
  --icon app.ico ^
  --add-data "app.ico;." ^
  main.py
echo.
echo 完成: dist\ClaudeUsageWidget.exe
pause
