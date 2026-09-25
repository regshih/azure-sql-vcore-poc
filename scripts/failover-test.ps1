& "$PSScriptRoot\Invoke-Poc.ps1" -Module src.operations.cli -Operation failover-test -Arguments $args
exit $LASTEXITCODE
