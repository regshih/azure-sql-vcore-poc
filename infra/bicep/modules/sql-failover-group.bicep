param serverName string
param failoverGroupName string
param primaryDatabaseId string
param secondaryServerId string
resource server 'Microsoft.Sql/servers@2023-08-01' existing = { name: serverName }
resource group 'Microsoft.Sql/servers/failoverGroups@2023-08-01' = {
  parent: server
  name: failoverGroupName
  properties: {
    readWriteEndpoint: { failoverPolicy: 'Manual' }
    readOnlyEndpoint: { failoverPolicy: 'Disabled' }
    partnerServers: [{ id: secondaryServerId }]
    databases: [primaryDatabaseId]
  }
}
output readWriteHost string = '${group.name}${environment().suffixes.sqlServerHostname}'
output readOnlyHost string = '${group.name}.secondary${environment().suffixes.sqlServerHostname}'
