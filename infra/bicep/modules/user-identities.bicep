param location string
param tags object
param resourcePrefix string

resource bootstrapIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-init-${resourcePrefix}'
  location: location
  tags: tags
}

resource runtimeIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-api-${resourcePrefix}'
  location: location
  tags: tags
}

resource runnerIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-run-${resourcePrefix}'
  location: location
  tags: tags
}

output bootstrapIdentityId string = bootstrapIdentity.id
output bootstrapIdentityPrincipalId string = bootstrapIdentity.properties.principalId
output bootstrapIdentityObjectId string = bootstrapIdentity.properties.principalId
output runtimeIdentityId string = runtimeIdentity.id
output runtimeIdentityPrincipalId string = runtimeIdentity.properties.principalId
output runnerIdentityId string = runnerIdentity.id
output runnerIdentityPrincipalId string = runnerIdentity.properties.principalId
output bootstrapIdentityClientId string = bootstrapIdentity.properties.clientId
output runtimeIdentityClientId string = runtimeIdentity.properties.clientId
output runnerIdentityClientId string = runnerIdentity.properties.clientId
