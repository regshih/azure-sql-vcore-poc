[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Module,
    [Parameter(Mandatory = $true)][string]$Operation,
    [string[]]$Arguments = @()
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    $python = Join-Path $root '.venv/bin/python'
}
if (-not (Test-Path $python)) {
    if ($env:PYTHON) { $python = $env:PYTHON }
    else { $python = (Get-Command python -ErrorAction Stop).Source }
}
Push-Location $root
try {
    & $python -m $Module $Operation @Arguments
    $result = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $result
