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
set "APP=%ROOT%\scoring_system\query_app.py"

echo Starting stock assistant...
echo Project: %ROOT%
echo Python: %PY%
echo App: %APP%
echo.

if not exist "%PY%" (
    echo ERROR: Python not found.
    pause
    exit /b 1
)

if not exist "%APP%" (
    echo ERROR: query_app.py not found.
    pause
    exit /b 1
)

"%PY%" "%APP%"
set "APP_EXIT=%ERRORLEVEL%"

if not "%APP_EXIT%"=="0" (
    echo.
    echo GUI failed to start. See the error above.
    pause
    exit /b %APP_EXIT%
)

endlocal
exit /b 0

