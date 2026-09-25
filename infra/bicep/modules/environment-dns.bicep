param domain string
param address string
param vnetId string
param tags object
resource zone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: domain
  location: 'global'
  tags: tags
}
resource link 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: zone
  name: 'environment'
  location: 'global'
  properties: { registrationEnabled: false, virtualNetwork: { id: vnetId } }
}
resource wildcard 'Microsoft.Network/privateDnsZones/A@2020-06-01' = {
  parent: zone
  name: '*'
  properties: { ttl: 60, aRecords: [{ ipv4Address: address }] }
}
