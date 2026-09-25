& "$PSScriptRoot\Invoke-Poc.ps1" -Module src.operations.cli -Operation deploy -Arguments $args
exit $LASTEXITCODE
