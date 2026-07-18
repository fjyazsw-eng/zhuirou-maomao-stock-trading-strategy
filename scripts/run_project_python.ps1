param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$PythonArgs
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$CodexPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (Test-Path -LiteralPath $VenvPython) {
  $Python = $VenvPython
} elseif (Test-Path -LiteralPath $CodexPython) {
  $Python = $CodexPython
} else {
  throw "No usable project Python found. Run scripts\check_codex_runtime_health.ps1 first."
}

Set-Location -LiteralPath $Root
& $Python @PythonArgs
exit $LASTEXITCODE
