param([switch]$StartNow)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Starter = Join-Path $Root 'scripts\start_realtime_watch_monitor_hidden.ps1'
$TaskName = 'stock-ai-realtime-watch-monitor'
$RunName = 'StockAIRealtimeWatchMonitor'
$RunPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$RunCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Starter`""
$Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Starter`""
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 3650)
$Method = 'scheduled_task'
try {
  Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description '股票AI交易助手只读实时盯盘，不接账户、不自动交易' -Force -ErrorAction Stop | Out-Null
} catch {
  New-Item -Path $RunPath -Force | Out-Null
  Set-ItemProperty -Path $RunPath -Name $RunName -Value $RunCommand
  $Method = 'current_user_run_key'
}
if ($StartNow) {
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Starter
}
[pscustomobject]@{
  installed = $true
  method = $Method
  scheduled_task = if ($Method -eq 'scheduled_task') { $TaskName } else { '' }
  run_key = if ($Method -eq 'current_user_run_key') { $RunName } else { '' }
}
