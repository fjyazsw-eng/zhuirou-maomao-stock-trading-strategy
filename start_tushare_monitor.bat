@echo off
setlocal
set "PROJECT_ROOT=%~dp0"
set "VENV_PYTHON=%PROJECT_ROOT%.venv\Scripts\python.exe"
set "CODEX_PYTHON=C:\Users\HUAWEI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

rem Project-scoped proxy cleanup for Tushare. This does not modify Windows user/system env.
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "ALL_PROXY="
set "http_proxy="
set "https_proxy="
set "all_proxy="
set "NO_PROXY=api.waditu.com,127.0.0.1,localhost"
set "no_proxy=api.waditu.com,127.0.0.1,localhost"

if exist "%VENV_PYTHON%" (
  set "PYTHON_EXE=%PROJECT_ROOT%.venv\Scripts\pythonw.exe"
) else if exist "%CODEX_PYTHON%" (
  set "PYTHON_EXE=%CODEX_PYTHON:python.exe=pythonw.exe%"
) else (
  echo ERROR: no usable Python found. Expected .venv or Codex bundled Python.
  pause
  exit /b 1
)

start "" "%PYTHON_EXE%" "%PROJECT_ROOT%scripts\run_tushare_monitor.py" %*
endlocal
