param(
  [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"

function Test-PythonCandidate {
  param([string]$Path)
  if (-not $Path -or -not (Test-Path -LiteralPath $Path)) {
    return $null
  }

  $version = & $Path --version 2>&1
  $exitCode = $LASTEXITCODE
  $isWindowsAppsShim = $Path -like "*\WindowsApps\python.exe"

  [pscustomobject]@{
    Path = $Path
    Exists = $true
    VersionOutput = ($version -join " ").Trim()
    ExitCode = $exitCode
    IsWindowsAppsShim = $isWindowsAppsShim
    Usable = ($exitCode -eq 0 -and -not $isWindowsAppsShim)
  }
}

Set-Location -LiteralPath $Root

$commandPython = Get-Command python -ErrorAction SilentlyContinue
$defaultPython = if ($commandPython) { $commandPython.Source } else { "" }
$codexPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$venvPython = Join-Path $Root ".venv\Scripts\python.exe"

$pythonChecks = @(
  (Test-PythonCandidate $venvPython),
  (Test-PythonCandidate $defaultPython),
  (Test-PythonCandidate $codexPython)
) | Where-Object { $_ -ne $null }

$usablePython = $pythonChecks | Where-Object { $_.Usable } | Select-Object -First 1

$contextPath = Join-Path $Root "PROJECT_CONTEXT.md"
$contextFirstLine = if (Test-Path -LiteralPath $contextPath) {
  $line = Get-Content -LiteralPath $contextPath -Encoding UTF8 -TotalCount 1
  if ($null -eq $line) { "" } else { $line.ToString() }
} else {
  ""
}

$report = [ordered]@{
  root = $Root
  project_context_utf8_first_line = $contextFirstLine
  default_python = $defaultPython
  python_checks = $pythonChecks
  recommended_python = if ($usablePython) { $usablePython.Path } else { "" }
  top_level_file_count_hint = (Get-ChildItem -LiteralPath $Root -File -ErrorAction SilentlyContinue | Measure-Object).Count
  guidance = @(
    "PowerShell reads Chinese project files with -Encoding UTF8.",
    "Avoid full rg --files output; narrow by directory or filename.",
    "Use recommended_python when default python is the WindowsApps shim."
  )
}

$report | ConvertTo-Json -Depth 5

if (-not $usablePython) {
  exit 1
}
