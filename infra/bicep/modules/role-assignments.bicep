param registryName string
param sqlServerName string
param sqlDatabaseName string
param storageAccountName string
param workspaceName string
param runtimePrincipalId string
param bootstrapPrincipalId string
param runnerPrincipalId string

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}
resource server 'Microsoft.Sql/servers@2023-08-01' existing = { name: sqlServerName }
resource database 'Microsoft.Sql/servers/databases@2023-08-01' existing = {
  parent: server
  name: sqlDatabaseName
}
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = { name: storageAccountName }
resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: storage
  name: 'default'
}
resource evidence 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = {
  parent: blobs
  name: 'evidence'
}
resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}
var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var blobContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var reader = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
var logReader = '73c42c96-874c-492b-b04d-ab87d138a893'

resource pulls 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principal in [
    runtimePrincipalId
    bootstrapPrincipalId
    runnerPrincipalId
  ]: {
    scope: registry
    name: guid(registry.id, principal, acrPull)
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
      principalId: principal
      principalType: 'ServicePrincipal'
    }
  }
]
resource upload 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: evidence
  name: guid(evidence.id, runnerPrincipalId, blobContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobContributor)
    principalId: runnerPrincipalId
    principalType: 'ServicePrincipal'
  }
}
resource metrics 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: database
  name: guid(database.id, runnerPrincipalId, reader)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', reader)
    principalId: runnerPrincipalId
    principalType: 'ServicePrincipal'
  }
}
resource queries 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: workspace
  name: guid(workspace.id, runnerPrincipalId, logReader)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', logReader)
    principalId: runnerPrincipalId
    principalType: 'ServicePrincipal'
  }
}
