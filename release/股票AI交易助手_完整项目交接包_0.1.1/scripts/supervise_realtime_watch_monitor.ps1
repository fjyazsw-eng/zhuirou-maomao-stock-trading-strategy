$ErrorActionPreference = 'Continue'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Runner = Join-Path $Root 'scripts\run_realtime_watch_monitor.py'
$LogDir = Join-Path $Root 'reports\realtime_watch'
$SupervisorLog = Join-Path $LogDir 'supervisor.log'

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location -LiteralPath $Root
while ($true) {
  & $Python $Runner --send
  $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  Add-Content -LiteralPath $SupervisorLog -Encoding UTF8 -Value "$stamp monitor exited code=$LASTEXITCODE; restarting in 10 seconds"
  Start-Sleep -Seconds 10
}
