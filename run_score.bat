@echo off
setlocal
set PROJECT_ROOT=%~dp0
set VENV_PYTHON=%PROJECT_ROOT%.venv\Scripts\python.exe
set CODEX_PYTHON=C:\Users\HUAWEI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe

if exist "%VENV_PYTHON%" (
  set PYTHON_EXE=%VENV_PYTHON%
) else if exist "%CODEX_PYTHON%" (
  echo Warning: using temporary Codex bundled Python. Please create project .venv for formal runs.
  set PYTHON_EXE=%CODEX_PYTHON%
) else (
  echo ERROR: no usable Python found. Expected .venv or Codex bundled Python.
  exit /b 1
)

"%PYTHON_EXE%" "%PROJECT_ROOT%scripts\run_score.py" %*
endlocal
