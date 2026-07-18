@echo off
cd /d "%~dp0"
echo Telegram 双向助手启动中...
echo 保持这个窗口打开，手机发消息才会自动回复。
if not exist "logs" mkdir logs
set "LOCAL_PY=%~dp0.venv\Scripts\python.exe"
set "CODEX_PY=C:\Users\HUAWEI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%LOCAL_PY%" (
  "%LOCAL_PY%" scripts\run_telegram_gateway.py 1>>logs\telegram_gateway.out.log 2>>logs\telegram_gateway.err.log
) else if exist "%CODEX_PY%" (
  "%CODEX_PY%" scripts\run_telegram_gateway.py 1>>logs\telegram_gateway.out.log 2>>logs\telegram_gateway.err.log
) else (
  python scripts\run_telegram_gateway.py 1>>logs\telegram_gateway.out.log 2>>logs\telegram_gateway.err.log
)
pause
