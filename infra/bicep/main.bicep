targetScope = 'subscription'

@minLength(3)
param resourceGroupName string
@minLength(3)
@maxLength(20)
param environmentName string
param location string
@allowed(['secure', 'evaluation'])
param deploymentProfile string = 'secure'
param allowEvaluationPublicAccess bool = false
param evaluationIp string = ''
param deployApplication bool = false
param image string = ''
@secure()
param internalApiToken string = ''
@allowed(['Provisioned', 'Serverless'])
param sqlComputeTier string = 'Provisioned'
@allowed([2, 4])
param sqlVcores int = 2
param sqlMinVcores string = '0.5'
@minValue(-1)
@maxValue(10080)
param sqlAutoPauseDelay int = -1
@minValue(1)
@maxValue(32)
param sqlMaxSizeGb int = 5
@allowed(['Gen5'])
param sqlHardwareFamily string = 'Gen5'
@allowed(['Local', 'Zone', 'Geo', 'GeoZone'])
param sqlBackupRedundancy string = 'Local'
param sqlZoneRedundant bool = false
param enableDr bool = false
param enableBusinessCritical bool = false
param enableLegacyRedis bool = false
param secondaryLocation string = ''
param enableSqlDiagnostics bool = false
param enableAlerts bool = false
param alertActionGroupIds array = []
param alertOwner string = 'TBD'
param alertRunbookBaseUrl string = ''
param alertThresholds object = {}

var prefix = environmentName
var publicEvaluation = deploymentProfile == 'evaluation' && allowEvaluationPublicAccess && !empty(evaluationIp)
var tags = {
  poc: 'sql-vcore'
  environment: 'poc'
  deploymentProfile: deploymentProfile
}
var appName = 'ca-${prefix}'
var initName = 'init-${prefix}'
var runnerName = 'run-${prefix}'
var primaryServerName = 'sql-${prefix}'
var secondaryServerName = 'sql-${prefix}-dr'
var failoverGroupName = 'fg-${prefix}'

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module identities './modules/user-identities.bicep' = {
  name: 'identities'
  scope: rg
  params: { location: location, tags: tags, resourcePrefix: prefix }
}
module logs './modules/log-analytics.bicep' = {
  name: 'logs'
  scope: rg
  params: { location: location, tags: tags, resourcePrefix: prefix }
}
module insights './modules/application-insights.bicep' = {
  name: 'insights'
  scope: rg
  params: {
    location: location
    tags: tags
    resourcePrefix: prefix
    workspaceId: logs.outputs.id
  }
}
module network './modules/network.bicep' = {
  name: 'network'
  scope: rg
  params: { location: location, tags: tags, resourcePrefix: prefix }
}
module storage './modules/storage.bicep' = {
  name: 'evidence'
  scope: rg
  params: {
    location: location
    tags: tags
    resourcePrefix: prefix
    privateEndpointsSubnetId: network.outputs.privateEndpointSubnetId
    privateDnsZoneId: network.outputs.privateDnsZoneBlobId
  }
}
module registry './modules/container-registry.bicep' = {
  name: 'registry'
  scope: rg
  params: { location: location, tags: tags, resourcePrefix: prefix }
}
module primary './modules/sql-database.bicep' = {
  name: 'sql-primary'
  scope: rg
  params: {
    location: location
    networkLocation: location
    tags: tags
    serverName: primaryServerName
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    privateDnsZoneId: network.outputs.privateDnsZoneId
    bootstrapIdentityObjectId: identities.outputs.bootstrapIdentityPrincipalId
    computeTier: sqlComputeTier
    vCores: sqlVcores
    minVCores: sqlMinVcores
    autoPauseDelay: sqlAutoPauseDelay
    maxSizeGb: sqlMaxSizeGb
    hardwareFamily: sqlHardwareFamily
    serviceTier: enableBusinessCritical ? 'BusinessCritical' : 'GeneralPurpose'
    backupRedundancy: sqlBackupRedundancy
    zoneRedundant: sqlZoneRedundant
    publicEvaluation: publicEvaluation
    evaluationIp: evaluationIp
    enableDiagnostics: enableSqlDiagnostics
    workspaceId: logs.outputs.id
  }
}
module secondary './modules/sql-database.bicep' = if (enableDr) {
  name: 'sql-secondary'
  scope: rg
  params: {
    location: secondaryLocation
    networkLocation: location
    tags: tags
    serverName: secondaryServerName
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    privateDnsZoneId: network.outputs.privateDnsZoneId
    bootstrapIdentityObjectId: identities.outputs.bootstrapIdentityPrincipalId
    computeTier: sqlComputeTier
    vCores: sqlVcores
    minVCores: sqlMinVcores
    autoPauseDelay: -1
    maxSizeGb: sqlMaxSizeGb
    hardwareFamily: sqlHardwareFamily
    serviceTier: enableBusinessCritical ? 'BusinessCritical' : 'GeneralPurpose'
    backupRedundancy: sqlBackupRedundancy
    zoneRedundant: sqlZoneRedundant
    sourceDatabaseId: primary.outputs.sqlDatabaseId
  }
}
module failover './modules/sql-failover-group.bicep' = if (enableDr) {
  name: 'failover-group'
  scope: rg
  params: {
    serverName: primaryServerName
    failoverGroupName: failoverGroupName
    primaryDatabaseId: primary.outputs.sqlDatabaseId
    secondaryServerId: secondary!.outputs.sqlServerId
  }
}
module environment './modules/container-app-environment.bicep' = {
  name: 'app-environment'
  scope: rg
  params: {
    location: location
    tags: tags
    resourcePrefix: prefix
    workspaceName: logs.outputs.name
    containerAppsSubnetId: network.outputs.containerAppsSubnetId
    internal: !publicEvaluation
    vnetId: network.outputs.vnetId
  }
}
module roles './modules/role-assignments.bicep' = {
  name: 'roles'
  scope: rg
  params: {
    registryName: registry.outputs.name
    sqlServerName: primaryServerName
    sqlDatabaseName: primary.outputs.sqlDatabaseName
    storageAccountName: storage.outputs.storageAccountName
    workspaceName: logs.outputs.name
    runtimePrincipalId: identities.outputs.runtimeIdentityPrincipalId
    bootstrapPrincipalId: identities.outputs.bootstrapIdentityPrincipalId
    runnerPrincipalId: identities.outputs.runnerIdentityPrincipalId
  }
}
module app './modules/container-app.bicep' = if (deployApplication) {
  name: 'api'
  scope: rg
  params: {
    location: location
    tags: tags
    appName: appName
    environmentId: environment.outputs.environmentId
    image: image
    acrLoginServer: registry.outputs.loginServer
    sqlServerHost: enableDr ? failover!.outputs.readWriteHost : primary.outputs.sqlServerHost
    sqlDatabaseName: primary.outputs.sqlDatabaseName
    runtimeIdentityId: identities.outputs.runtimeIdentityId
    runtimeClientId: identities.outputs.runtimeIdentityClientId
    runtimePrincipalId: identities.outputs.runtimeIdentityPrincipalId
    redisHost: enableLegacyRedis ? redis!.outputs.host : ''
    appInsightsName: insights.outputs.name
    internalApiToken: internalApiToken
    publicEvaluation: publicEvaluation
    evaluationIp: evaluationIp
    computeTier: sqlComputeTier
    vcores: sqlVcores
  }
  dependsOn: [roles]
}
module redis './modules/redis-optional.bicep' = if (enableLegacyRedis) {
  name: 'legacy-redis-extension'
  scope: rg
  params: {
    location: location
    tags: tags
    name: 'redis-${prefix}'
    runtimePrincipalId: identities.outputs.runtimeIdentityPrincipalId
    vnetId: network.outputs.vnetId
    subnetId: network.outputs.privateEndpointSubnetId
  }
}
module jobs './modules/container-app-jobs.bicep' = if (deployApplication) {
  name: 'jobs'
  scope: rg
  params: {
    location: location
    tags: tags
    initName: initName
    runnerName: runnerName
    environmentName: environmentName
    environmentId: environment.outputs.environmentId
    image: image
    acrLoginServer: registry.outputs.loginServer
    bootstrapIdentityId: identities.outputs.bootstrapIdentityId
    bootstrapClientId: identities.outputs.bootstrapIdentityClientId
    runtimeClientId: identities.outputs.runtimeIdentityClientId
    runnerIdentityId: identities.outputs.runnerIdentityId
    runnerClientId: identities.outputs.runnerIdentityClientId
    sqlServerHost: primary.outputs.sqlServerHost
    sqlDatabaseName: primary.outputs.sqlDatabaseName
    sqlResourceId: primary.outputs.sqlDatabaseId
    appUrl: 'https://${app!.outputs.fqdn}'
    storageAccountName: storage.outputs.storageAccountName
    workspaceCustomerId: logs.outputs.customerId
    internalApiToken: internalApiToken
  }
  dependsOn: [roles]
}
module alerts './modules/alerts.bicep' = {
  name: 'alerts'
  scope: rg
  params: {
    enabled: enableAlerts
    tags: tags
    databaseId: primary.outputs.sqlDatabaseId
    databaseLocation: location
    prefix: prefix
    workspaceId: logs.outputs.id
    serverless: sqlComputeTier == 'Serverless'
    actionGroupIds: alertActionGroupIds
    owner: alertOwner
    runbookBaseUrl: alertRunbookBaseUrl
    thresholds: alertThresholds
  }
}

output deployment object = {
  resource_group: rg.name
  region: location
  sql_server: primaryServerName
  database: primary.outputs.sqlDatabaseName
  app_name: appName
  runner_job: runnerName
  init_job: initName
  workspace_id: logs.outputs.customerId
  workspace_resource_id: logs.outputs.id
  registry_name: registry.outputs.name
  registry_login_server: registry.outputs.loginServer
  app_url: deployApplication ? 'https://${app!.outputs.fqdn}' : ''
  bootstrap_client_id: identities.outputs.bootstrapIdentityClientId
  runtime_client_id: identities.outputs.runtimeIdentityClientId
  runtime_object_id: identities.outputs.runtimeIdentityPrincipalId
  evidence_storage_account: storage.outputs.storageAccountName
  evidence_storage_container: storage.outputs.containerName
  secondary_server: enableDr ? secondaryServerName : ''
  failover_group: enableDr ? failoverGroupName : ''
}
