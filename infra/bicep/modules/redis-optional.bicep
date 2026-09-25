// Legacy compatibility requested by the POC. Prefer Azure Managed Redis for new deployments.
param location string
param tags object
param name string
param runtimePrincipalId string
param vnetId string
param subnetId string

resource cache 'Microsoft.Cache/redis@2024-11-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    sku: { name: 'Standard', family: 'C', capacity: 1 }
    redisVersion: '6'
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Disabled'
    disableAccessKeyAuthentication: true
    redisConfiguration: {
      'aad-enabled': 'true'
      'maxmemory-policy': 'allkeys-lru'
    }
  }
}
resource access 'Microsoft.Cache/redis/accessPolicyAssignments@2024-11-01' = {
  parent: cache
  name: 'poc-runtime'
  properties: {
    accessPolicyName: 'Data Contributor'
    objectId: runtimePrincipalId
    objectIdAlias: 'poc-runtime'
  }
}
resource zone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.redis.cache.windows.net'
  location: 'global'
  tags: tags
}
resource link 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: zone
  name: 'poc-network'
  location: 'global'
  properties: { registrationEnabled: false, virtualNetwork: { id: vnetId } }
}
resource endpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-${name}'
  location: location
  tags: tags
  properties: {
    subnet: { id: subnetId }
    privateLinkServiceConnections: [{
      name: 'redis'
      properties: { privateLinkServiceId: cache.id, groupIds: ['redisCache'] }
    }]
  }
}
resource dns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: endpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [{ name: 'redis', properties: { privateDnsZoneId: zone.id } }]
  }
}
output host string = cache.properties.hostName
