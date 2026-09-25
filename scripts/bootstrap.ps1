& "$PSScriptRoot\Invoke-Poc.ps1" -Module src.operations.cli -Operation bootstrap -Arguments $args
exit $LASTEXITCODE
