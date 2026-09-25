& "$PSScriptRoot\Invoke-Poc.ps1" -Module src.operations.cli -Operation destroy -Arguments $args
exit $LASTEXITCODE
