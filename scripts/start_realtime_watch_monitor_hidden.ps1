$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Runner = Join-Path $Root 'scripts\run_realtime_watch_monitor.py'
$Supervisor = Join-Path $Root 'scripts\supervise_realtime_watch_monitor.ps1'
$LogDir = Join-Path $Root 'reports\realtime_watch'
$OutLog = Join-Path $LogDir 'monitor.out.log'
$ErrLog = Join-Path $LogDir 'monitor.err.log'

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
if (-not (Test-Path -LiteralPath $Python)) {
  throw "可用 Python 不存在：$Python"
}

$existing = Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -match [regex]::Escape('supervise_realtime_watch_monitor.ps1') -or
  ($_.Name -eq 'python.exe' -and $_.CommandLine -match [regex]::Escape('run_realtime_watch_monitor.py'))
}
if ($existing) {
  exit 0
}

Start-Process -FilePath 'powershell.exe' `
  -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Supervisor) `
  -WorkingDirectory $Root `
  -WindowStyle Hidden `
  -RedirectStandardOutput $OutLog `
  -RedirectStandardError $ErrLog
