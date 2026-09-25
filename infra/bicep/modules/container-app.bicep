param location string
param tags object
param appName string
param environmentId string
@minLength(1)
param image string
param acrLoginServer string
param sqlServerHost string
param sqlDatabaseName string
param runtimeIdentityId string
param runtimeClientId string
param runtimePrincipalId string
param redisHost string = ''
param appInsightsName string
@secure()
@minLength(32)
param internalApiToken string
param publicEvaluation bool
param evaluationIp string
param computeTier string
param vcores int

// Workload-profile pod ranges are not RFC1918; the bearer token remains mandatory.
var internalAllowedNetworks = [
  '127.0.0.0/8'
  '::1/128'
  '10.0.0.0/8'
  '172.16.0.0/12'
  '192.168.0.0/16'
  '100.100.0.0/17'
  '100.100.128.0/19'
  '100.100.160.0/19'
  '100.100.192.0/19'
]
var applicationEnvironment = [
  { name: 'PORT', value: '8000' }
  { name: 'HOST', value: '0.0.0.0' }
  { name: 'APP_ENVIRONMENT', value: 'production' }
  { name: 'REPOSITORY_BACKEND', value: 'sql' }
  { name: 'SQL_SERVER', value: sqlServerHost }
  { name: 'SQL_DATABASE', value: sqlDatabaseName }
  { name: 'AZURE_CLIENT_ID', value: runtimeClientId }
  { name: 'INTERNAL_API_TOKEN', secretRef: 'internal-api-token' }
  { name: 'INTERNAL_ALLOWED_NETWORKS', value: string(internalAllowedNetworks) }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.properties.ConnectionString }
  { name: 'DEPLOYMENT_REGION', value: location }
  { name: 'COMPUTE_TIER', value: toLower(computeTier) }
  { name: 'VCORE_CONFIGURATION', value: string(vcores) }
  { name: 'DATABASE_PROFILE', value: '${toLower(computeTier)}-${vcores}' }
  { name: 'CACHE_BACKEND', value: empty(redisHost) ? 'disabled' : 'redis' }
  { name: 'ALLOW_UNSAFE_TESTS', value: 'false' }
]
var redisEnvironment = empty(redisHost) ? [] : [
  { name: 'REDIS_HOST', value: redisHost }
  { name: 'REDIS_USERNAME', value: runtimePrincipalId }
  { name: 'REDIS_PORT', value: '6380' }
]

resource insights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}
resource app 'Microsoft.App/containerApps@2025-01-01' = {
  name: appName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${runtimeIdentityId}': {} }
  }
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        // External to the app, but still private within an internal environment.
        external: true
        allowInsecure: false
        targetPort: 8000
        transport: 'http'
        ipSecurityRestrictions: publicEvaluation
          ? [
              {
                name: 'evaluation-caller'
                action: 'Allow'
                ipAddressRange: '${evaluationIp}/32'
              }
            ]
          : []
      }
      registries: [{ server: acrLoginServer, identity: runtimeIdentityId }]
      secrets: [{ name: 'internal-api-token', value: internalApiToken }]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: image
          env: concat(applicationEnvironment, redisEnvironment)
          resources: { cpu: json('0.5'), memory: '1Gi' }
          // Process-only platform probes permit bootstrap and serverless idle.
          // The smoke job verifies SQL readiness separately.
          probes: [
            for kind in ['Liveness', 'Readiness']: {
              type: kind
              httpGet: { path: '/healthz', port: 8000, scheme: 'HTTP' }
              initialDelaySeconds: 10
              periodSeconds: 15
              timeoutSeconds: 3
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 1 }
      terminationGracePeriodSeconds: 30
    }
  }
}
output fqdn string = app.properties.configuration.ingress.fqdn
