param location string
param tags object
param resourcePrefix string
param workspaceName string
param containerAppsSubnetId string
param internal bool
param vnetId string

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}
resource environment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: 'cae-${resourcePrefix}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspace.properties.customerId
        sharedKey: workspace.listKeys().primarySharedKey
      }
    }
    vnetConfiguration: {
      infrastructureSubnetId: containerAppsSubnetId
      internal: internal
    }
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
  }
}
module dns './environment-dns.bicep' = if (internal) {
  name: 'internal-environment-dns'
  params: {
    domain: environment.properties.defaultDomain
    address: environment.properties.staticIp
    vnetId: vnetId
    tags: tags
  }
}
output environmentId string = environment.id
