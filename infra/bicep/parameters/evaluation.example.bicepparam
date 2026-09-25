using '../main.bicep'

// Explicit public evaluation only; replace the placeholder with one public IPv4.
// The guarded Python configuration validator rejects private addresses and CIDRs.
param resourceGroupName = 'rg-replace-with-poc-name'
param environmentName = 'replace-with-name'
param location = 'centralus'
param deploymentProfile = 'evaluation'
param allowEvaluationPublicAccess = true
param evaluationIp = 'REPLACE_PUBLIC_IPV4'
param deployApplication = false
param sqlComputeTier = 'Provisioned'
param sqlVcores = 2
param sqlMaxSizeGb = 5
