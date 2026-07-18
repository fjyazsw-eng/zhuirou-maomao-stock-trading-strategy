@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"
rem Project-scoped proxy cleanup for Tushare. This does not modify Windows user/system env.
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "ALL_PROXY="
set "http_proxy="
set "https_proxy="
set "all_proxy="
set "NO_PROXY=api.waditu.com,127.0.0.1,localhost"
set "no_proxy=api.waditu.com,127.0.0.1,localhost"

set "PY=%ROOT%\.venv\Scripts\python.exe"
set "LOGDIR=%ROOT%\logs"
set "LOG=%LOGDIR%\daily_simulation_latest.log"
set "STATUS=%ROOT%\reports\simulation\latest_run_status.md"
set "STATUS_HTML=%ROOT%\reports\simulation\latest_run_status.html"
set "TMP_OUT=%TEMP%\daily_simulation_output_%RANDOM%.log"

if not exist "%LOGDIR%" mkdir "%LOGDIR%" >nul 2>nul

echo [1/4] Using project Python:
echo "%PY%"

> "%LOG%" echo run_time=%DATE% %TIME%
>> "%LOG%" echo python_path=%PY%

if not exist "%PY%" (
    >> "%LOG%" echo error=project .venv python not found
    echo Project .venv Python not found: "%PY%"
    pause
    exit /b 1
)

echo [2/4] Online update, then run daily simulation...
"%PY%" scripts\run_daily_simulation.py --online-update > "%TMP_OUT%" 2>&1
set "RUN_EXIT=%ERRORLEVEL%"

echo [3/4] Writing short log...
"%PY%" scripts\write_daily_simulation_log.py --status "%STATUS%" --temp-output "%TMP_OUT%" --log "%LOG%" --exit-code "%RUN_EXIT%"

if exist "%TMP_OUT%" del "%TMP_OUT%" >nul 2>nul

if exist "%STATUS%" (
    echo [4/4] Opening latest status report...
    if "%DAILY_SIMULATION_NO_OPEN%"=="" (
        if exist "%STATUS_HTML%" (
            start "" "%STATUS_HTML%"
        ) else (
            start "" "%STATUS%"
        )
    )
) else (
    echo latest_run_status.md was not generated. See "%LOG%"
)

if not "%RUN_EXIT%"=="0" (
    echo Daily simulation failed. See "%LOG%"
    pause
)

if "%RUN_EXIT%"=="0" (
    echo Daily simulation finished. Log: "%LOG%"
)

exit /b %RUN_EXIT%

