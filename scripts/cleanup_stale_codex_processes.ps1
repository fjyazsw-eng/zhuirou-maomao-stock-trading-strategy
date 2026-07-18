param(
    [switch]$Kill,
    [int]$MinAgeMinutes = 30,
    [double]$MinCpuSeconds = 60
)

$now = Get-Date
$workspace = (Resolve-Path "$PSScriptRoot\..").Path

$candidates = Get-Process python,python3,py -ErrorAction SilentlyContinue |
    Where-Object {
        $_.StartTime -and
        (($now - $_.StartTime).TotalMinutes -ge $MinAgeMinutes) -and
        ($_.CPU -ge $MinCpuSeconds)
    } |
    Select-Object Id,ProcessName,CPU,StartTime,Path

if (-not $candidates) {
    Write-Output "No stale Python processes matched MinAgeMinutes=$MinAgeMinutes MinCpuSeconds=$MinCpuSeconds."
    exit 0
}

Write-Output "Stale Python process candidates:"
$candidates | Format-Table -AutoSize

if (-not $Kill) {
    Write-Output "Dry run only. Re-run with -Kill to stop these processes."
    exit 0
}

foreach ($process in $candidates) {
    Stop-Process -Id $process.Id -Force
    Write-Output "Stopped process $($process.Id) $($process.ProcessName)."
}
