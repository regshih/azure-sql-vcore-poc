$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot '..')
try {
    if ($env:PYTHON) {
        $pythonExecutable = $env:PYTHON
    } elseif (Test-Path '.venv\Scripts\python.exe') {
        $pythonExecutable = '.venv\Scripts\python.exe'
    } elseif (Test-Path '.venv/bin/python') {
        $pythonExecutable = '.venv/bin/python'
    } else {
        $pythonExecutable = 'python3.12'
    }
    & $pythonExecutable -m src.operations.validate @args
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $code
