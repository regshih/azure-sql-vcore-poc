param enabled bool = false
param tags object
param prefix string
param databaseId string
param databaseLocation string
param workspaceId string
param serverless bool = false
param actionGroupIds array = []
param owner string = 'TBD'
param runbookBaseUrl string = ''
param thresholds object = {}

var limits = union({
  cpu: 80
  dataIo: 80
  logIo: 80
  workers: 80
  sessions: 80
  failedConnections: 0
  deadlocks: 0
  storage: 80
  serverlessCpu: 90
  p95Milliseconds: 500
  errorPercent: 1
  retryPercent: 5
  minimumRequests: 100
}, thresholds)
var description = 'POC starting point, not a universal production threshold. Inspect correlated evidence, classify the cause, and review noise/maintenance suppression before enabling. Owner: ${owner}. Runbook: ${runbookBaseUrl}/alerting-guide.md'
var metricSignals = [
  { name: 'cpu_percent', threshold: limits.cpu, aggregation: 'Average', window: 'PT10M' }
  { name: 'physical_data_read_percent', threshold: limits.dataIo, aggregation: 'Average', window: 'PT10M' }
  { name: 'log_write_percent', threshold: limits.logIo, aggregation: 'Average', window: 'PT10M' }
  { name: 'workers_percent', threshold: limits.workers, aggregation: 'Maximum', window: 'PT5M' }
  { name: 'sessions_percent', threshold: limits.sessions, aggregation: 'Maximum', window: 'PT5M' }
  { name: 'connection_failed', threshold: limits.failedConnections, aggregation: 'Total', window: 'PT5M' }
  { name: 'deadlock', threshold: limits.deadlocks, aggregation: 'Total', window: 'PT5M' }
  { name: 'storage_percent', threshold: limits.storage, aggregation: 'Maximum', window: 'PT15M' }
  { name: 'app_cpu_percent', threshold: limits.serverlessCpu, aggregation: 'Average', window: 'PT5M' }
]
resource pressure 'Microsoft.Insights/metricAlerts@2018-03-01' = [for signal in metricSignals: if (signal.name != 'app_cpu_percent' || serverless) {
  name: '${prefix}-${signal.name}'
  location: 'global'
  tags: union(tags, { owner: owner })
  properties: {
    enabled: enabled
    description: '${description}. Serverless CPU is a demand proxy, not proof of allocated cores.'
    severity: contains(['connection_failed', 'deadlock'], signal.name) ? 3 : 2
    scopes: [databaseId]
    targetResourceType: 'Microsoft.Sql/servers/databases'
    targetResourceRegion: databaseLocation
    evaluationFrequency: 'PT1M'
    windowSize: signal.window
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [{
        name: 'pressure'
        criterionType: 'StaticThresholdCriterion'
        metricNamespace: 'Microsoft.Sql/servers/databases'
        metricName: signal.name
        operator: 'GreaterThan'
        threshold: signal.threshold
        timeAggregation: signal.aggregation
      }]
    }
    actions: [for id in actionGroupIds: { actionGroupId: id }]
  }
}]
var appSignals = [
  {
    name: 'api-p95'
    threshold: limits.p95Milliseconds
    query: 'AppRequests | where TimeGenerated > ago(5m) | summarize N=count(), Value=percentile(DurationMs,95) | where N >= ${limits.minimumRequests} | project Value'
  }
  {
    name: 'api-error-rate'
    threshold: limits.errorPercent
    query: 'AppRequests | where TimeGenerated > ago(5m) | summarize N=sum(ItemCount), Failures=sumif(ItemCount,Success == false) | where N >= ${limits.minimumRequests} | project Value=100.0*Failures/N'
  }
  {
    name: 'api-retry-rate'
    threshold: limits.retryPercent
    query: 'ContainerAppConsoleLogs_CL | where TimeGenerated > ago(5m) | extend e=parse_json(Log_s) | where tostring(e.event) == "operation_final" | summarize N=count(), Retried=countif(toint(e.retry_count)>0) | where N >= ${limits.minimumRequests} | project Value=100.0*Retried/N'
  }
]
resource application 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = [for signal in appSignals: if (enabled) {
  name: '${prefix}-${signal.name}'
  location: databaseLocation
  tags: union(tags, { owner: owner })
  properties: {
    enabled: enabled
    description: '${description}. Validate actual table schema and ingestion before enabling.'
    severity: signal.name == 'api-retry-rate' ? 3 : 2
    scopes: [workspaceId]
    evaluationFrequency: 'PT1M'
    windowSize: 'PT5M'
    skipQueryValidation: true
    autoMitigate: true
    criteria: {
      allOf: [{
        query: signal.query
        timeAggregation: 'Maximum'
        metricMeasureColumn: 'Value'
        operator: 'GreaterThan'
        threshold: signal.threshold
        failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
      }]
    }
    actions: { actionGroups: actionGroupIds }
  }
}]
resource availability 'Microsoft.Insights/activityLogAlerts@2020-10-01' = {
  name: '${prefix}-availability'
  location: 'global'
  tags: union(tags, { owner: owner, severity: '4' })
  properties: {
    enabled: enabled
    description: '${description}. Check Resource Health and measured client recovery.'
    scopes: [databaseId]
    condition: { allOf: [{ field: 'category', equals: 'ResourceHealth' }] }
    actions: { actionGroups: [for id in actionGroupIds: { actionGroupId: id }] }
  }
}
resource failover 'Microsoft.Insights/activityLogAlerts@2020-10-01' = {
  name: '${prefix}-failover'
  location: 'global'
  tags: union(tags, { owner: owner, severity: '4' })
  properties: {
    enabled: enabled
    description: '${description}. Event-driven: correlate the approved operation with listener role and stable client recovery.'
    scopes: [resourceGroup().id]
    condition: {
      allOf: [
        { field: 'category', equals: 'Administrative' }
        {
          anyOf: [
            { field: 'operationName', equals: 'Microsoft.Sql/servers/databases/failover/action' }
            { field: 'operationName', equals: 'Microsoft.Sql/servers/failoverGroups/failover/action' }
            { field: 'operationName', equals: 'Microsoft.Sql/servers/failoverGroups/forceFailoverAllowDataLoss/action' }
          ]
        }
      ]
    }
    actions: { actionGroups: [for id in actionGroupIds: { actionGroupId: id }] }
  }
}
