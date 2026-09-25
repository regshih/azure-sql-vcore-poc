param location string
param networkLocation string
param tags object
param serverName string
param privateEndpointSubnetId string
param privateDnsZoneId string
param bootstrapIdentityObjectId string
param computeTier string = 'Provisioned'
param vCores int = 2
param minVCores string = '0.5'
param autoPauseDelay int = -1
param maxSizeGb int = 5
param hardwareFamily string = 'Gen5'
@allowed(['GeneralPurpose', 'BusinessCritical'])
param serviceTier string = 'GeneralPurpose'
param backupRedundancy string = 'Local'
param zoneRedundant bool = false
param publicEvaluation bool = false
param evaluationIp string = ''
param sourceDatabaseId string = ''
param enableDiagnostics bool = false
param workspaceId string = ''

resource server 'Microsoft.Sql/servers@2023-08-01' = {
  name: serverName
  location: location
  tags: tags
  properties: {
    version: '12.0'
    administrators: {
      administratorType: 'ActiveDirectory'
      principalType: 'Application'
      login: 'poc-bootstrap'
      sid: bootstrapIdentityObjectId
      tenantId: subscription().tenantId
      azureADOnlyAuthentication: true
    }
    minimalTlsVersion: '1.2'
    publicNetworkAccess: publicEvaluation ? 'Enabled' : 'Disabled'
    restrictOutboundNetworkAccess: 'Disabled'
  }
}
resource firewall 'Microsoft.Sql/servers/firewallRules@2023-08-01' = if (publicEvaluation) {
  parent: server
  name: 'explicit-evaluation-caller'
  properties: { startIpAddress: evaluationIp, endIpAddress: evaluationIp }
}
resource database 'Microsoft.Sql/servers/databases@2023-08-01' = {
  parent: server
  name: 'poc'
  location: location
  tags: tags
  sku: {
    name: serviceTier == 'BusinessCritical' ? 'BC_${hardwareFamily}' : (computeTier == 'Serverless' ? 'GP_S_${hardwareFamily}' : 'GP_${hardwareFamily}')
    tier: serviceTier
    family: hardwareFamily
    capacity: vCores
  }
  properties: {
    createMode: empty(sourceDatabaseId) ? 'Default' : 'Secondary'
    sourceDatabaseId: empty(sourceDatabaseId) ? null : sourceDatabaseId
    maxSizeBytes: maxSizeGb * 1073741824
    collation: 'SQL_Latin1_General_CP1_CI_AS'
    zoneRedundant: zoneRedundant
    readScale: 'Disabled'
    requestedBackupStorageRedundancy: backupRedundancy
    minCapacity: computeTier == 'Serverless' ? json(minVCores) : null
    autoPauseDelay: computeTier == 'Serverless' ? autoPauseDelay : null
  }
}
resource retention 'Microsoft.Sql/servers/databases/backupShortTermRetentionPolicies@2023-08-01' = {
  parent: database
  name: 'default'
  properties: { retentionDays: 7 }
}
resource endpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-${serverName}'
  location: networkLocation
  tags: tags
  properties: {
    subnet: { id: privateEndpointSubnetId }
    privateLinkServiceConnections: [
      {
        name: 'sql'
        properties: { privateLinkServiceId: server.id, groupIds: ['sqlServer'] }
      }
    ]
  }
}
resource dns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: endpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [{ name: 'sql', properties: { privateDnsZoneId: privateDnsZoneId } }]
  }
}
resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableDiagnostics) {
  scope: database
  name: 'poc-diagnostics'
  properties: {
    workspaceId: workspaceId
    logs: [
      { category: 'Errors', enabled: true }
      { category: 'Timeouts', enabled: true }
      { category: 'Blocks', enabled: true }
      { category: 'Deadlocks', enabled: true }
    ]
    metrics: [{ category: 'AllMetrics', enabled: true }]
  }
}
output sqlServerId string = server.id
output sqlServerHost string = server.properties.fullyQualifiedDomainName
output sqlDatabaseName string = database.name
output sqlDatabaseId string = database.id
