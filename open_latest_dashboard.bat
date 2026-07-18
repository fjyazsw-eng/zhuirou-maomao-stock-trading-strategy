@echo off
setlocal
set "FILE=%~dp0reports\latest_market_decision_dashboard.html"
if not exist "%FILE%" (
  echo latest_market_decision_dashboard.html not found.
  exit /b 1
)
start "" "%FILE%"
