$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    if ($env:PYTHON) { $python = $env:PYTHON }
    elseif (Get-Command python3 -ErrorAction SilentlyContinue) { $python = 'python3' }
    else { $python = 'python' }
}
Push-Location $root
try { & $python -m src.experiments.evidence @args; $result = $LASTEXITCODE }
finally { Pop-Location }
exit $result
