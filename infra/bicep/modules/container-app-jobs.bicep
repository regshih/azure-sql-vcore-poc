param location string
param tags object
param initName string
param runnerName string
param environmentName string
param environmentId string
@minLength(1)
param image string
param acrLoginServer string
param bootstrapIdentityId string
param bootstrapClientId string
param runtimeClientId string
param runnerIdentityId string
param runnerClientId string
param sqlServerHost string
param sqlDatabaseName string
param sqlResourceId string
param appUrl string
param storageAccountName string
param workspaceCustomerId string
@secure()
@minLength(32)
param internalApiToken string

resource bootstrap 'Microsoft.App/jobs@2025-01-01' = {
  name: initName
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${bootstrapIdentityId}': {} } }
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 3600
      replicaRetryLimit: 0
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [{ server: acrLoginServer, identity: bootstrapIdentityId }]
    }
    template: {
      containers: [
        {
          name: 'bootstrap'
          image: image
          command: ['python', '-m', 'src.database.manage']
          args: ['bootstrap', '--size', 'small', '--seed', '42']
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'APP_ENVIRONMENT', value: 'production' }
            { name: 'REPOSITORY_BACKEND', value: 'sql' }
            { name: 'SQL_SERVER', value: sqlServerHost }
            { name: 'SQL_DATABASE', value: sqlDatabaseName }
            { name: 'AZURE_CLIENT_ID', value: bootstrapClientId }
            { name: 'RUNTIME_CLIENT_ID', value: runtimeClientId }
            { name: 'OBSERVER_CLIENT_ID', value: runnerClientId }
          ]
        }
      ]
    }
  }
}
resource runner 'Microsoft.App/jobs@2025-01-01' = {
  name: runnerName
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${runnerIdentityId}': {} } }
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 14400
      replicaRetryLimit: 0
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [{ server: acrLoginServer, identity: runnerIdentityId }]
      secrets: [{ name: 'internal-api-token', value: internalApiToken }]
    }
    template: {
      containers: [
        {
          name: 'runner'
          image: image
          command: ['python', '-m', 'src.experiments.cloud_job']
          args: ['--profile', 'smoke']
          resources: { cpu: 1, memory: '2Gi' }
          env: [
            { name: 'APP_ENVIRONMENT', value: 'production' }
            { name: 'AZURE_CLIENT_ID', value: runnerClientId }
            { name: 'POC_INTERNAL_API_TOKEN', secretRef: 'internal-api-token' }
            { name: 'POC_HOST', value: appUrl }
            { name: 'SQL_SERVER', value: sqlServerHost }
            { name: 'SQL_DATABASE', value: sqlDatabaseName }
            { name: 'SQL_RESOURCE_ID', value: sqlResourceId }
            { name: 'AZURE_SUBSCRIPTION_ID', value: subscription().subscriptionId }
            { name: 'POC_RESOURCE_GROUP', value: resourceGroup().name }
            { name: 'POC_REGION', value: location }
            { name: 'POC_ENVIRONMENT_NAME', value: environmentName }
            { name: 'LOG_ANALYTICS_WORKSPACE_ID', value: workspaceCustomerId }
            { name: 'EVIDENCE_STORAGE_ACCOUNT', value: storageAccountName }
            { name: 'EVIDENCE_STORAGE_CONTAINER', value: 'evidence' }
          ]
        }
      ]
    }
  }
}
