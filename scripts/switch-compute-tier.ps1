& "$PSScriptRoot\Invoke-Poc.ps1" -Module src.operations.cli -Operation switch-compute-tier -Arguments $args
exit $LASTEXITCODE
