using '../main.bicep'

// POC assumptions only. Choose a unique name and an approved region before use.
// Prefer the guarded Python deploy command for complete image/bootstrap orchestration.
param resourceGroupName = 'rg-replace-with-poc-name'
param environmentName = 'replace-with-name'
param location = 'centralus'
param deploymentProfile = 'secure'
param deployApplication = false
param sqlComputeTier = 'Provisioned'
param sqlVcores = 2
param sqlMaxSizeGb = 5
