$ErrorActionPreference = 'Continue'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Runner = Join-Path $Root 'scripts\run_realtime_watch_monitor.py'
$LogDir = Join-Path $Root 'reports\realtime_watch'
$SupervisorLog = Join-Path $LogDir 'supervisor.log'

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location -LiteralPath $Root
while ($true) {
  $now = Get-Date
  $isWeekday = $now.DayOfWeek -notin @('Saturday', 'Sunday')
  $hhmm = $now.ToString('HH:mm')
  $inSession = $isWeekday -and (($hhmm -ge '09:25' -and $hhmm -le '11:35') -or ($hhmm -ge '12:55' -and $hhmm -le '15:05'))
  if ($inSession) {
    & $Python $Runner --send --session-only
    if ($LASTEXITCODE -ne 0) {
      $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
      Add-Content -LiteralPath $SupervisorLog -Encoding UTF8 -Value "$stamp monitor exited code=$LASTEXITCODE during trading session"
      Start-Sleep -Seconds 10
      continue
    }
    Start-Sleep -Seconds 30
    continue
  }
  Start-Sleep -Seconds 60
}
