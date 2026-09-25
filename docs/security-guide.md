# Security and identity guide

This is a design/runbook, not a security audit or certification. Customer identity,
network, data-classification and compliance requirements are **TBD**. Default
controls are a **POC assumption, not a confirmed customer requirement.**
Live control effectiveness: **Not demonstrated by this POC run.**

## Trust and identities

| Principal | Intended privilege | Prohibited runtime use |
| --- | --- | --- |
| Deployment operator/federated workflow | Approved resource deployment and scoped role assignment | Do not use a broad deployment identity for API SQL requests |
| SQL bootstrap managed identity | Entra-only SQL administrator for initialization, migration/seed/grants | No application traffic; review continued admin assignment after setup |
| API runtime managed identity | Least-privilege contained user for required reads/writes | No ownership, schema changes, SQL admin, role assignment or resource management |
| Workload runner identity | Reach approved API; SQL-resource Reader and workspace Log Analytics Reader for REST monitoring | No automatic SQL diagnostic/admin or cloud mutation rights; monitor reads do not grant SQL database access |
| Evidence writer | Runner-managed identity with scoped Storage Blob Data Contributor | No account-key use, public blob access or automatic operator write privileges |
| Evidence download operator | Separately approved blob read/list role and private network access | Do not assume deployment or SQL roles grant blob data access |
| Diagnostic operator | Time-bounded approved monitoring/SQL state visibility | Do not enlarge runtime rights just to collect DMVs |

DefaultAzureCredential uses the approved local developer identity outside Azure
and managed identity in Azure. Confirm the intended identity privately. Acquire
Azure SQL audience tokens without printing or persisting them. SQL tokens are
not passwords or connection strings and still require careful in-memory handling.
Authorization requires a corresponding contained database user/grants.
Cloud evidence REST and Blob credential paths are specifically constrained to
managed identity, with no environment-secret, CLI or browser fallback. The REST
collector requests separate ARM and Log Analytics audience tokens; neither is
a SQL token or the internal API shared bearer secret. Missing monitoring access
must produce explicit coverage failure, not privilege escalation.

The separate initialization job runs migrations, deterministic seed and contained
runtime-user setup. Validate initialization completion and effective runtime
permissions. Minimize bootstrap privileges over time according to the approved
maintenance model; do not casually remove required access before testing future
migrations. Use separate approval and identity for later schema changes.

## Network profiles

**Customer-secure default:** SQL public network disabled; approved private
endpoint and private DNS; internal Container Apps environment/private ingress;
approved VNet route for clients, jobs and administration. Validate private DNS
from every caller and both regions if DR is enabled. TLS encryption and
certificate validation remain required on private networks.

**Explicit evaluation opt-in:** temporary exact caller IPv4 SQL firewall and
matching app ingress restriction, approved time window and cleanup. Never use
an all-address firewall, broad CIDR, or “Allow Azure services.” Do not retry a
failed secure deployment by weakening access. Remove temporary rules and verify
public access disabled afterward.

Private SQL/API/Blob connectivity does not mean every supporting service has a
private endpoint. ACR Basic uses an authenticated public endpoint with anonymous
and admin access disabled. Private ACR would require the separately approved
Premium tier and additional networking/cost. Application Insights uses public
SDK ingestion configured through its telemetry connection string, not a SQL
connection string or SQL password. Stored telemetry is not thereby public.
The infrastructure resolves the Log Analytics shared key internally via
`listKeys`; it is not a deployment output. Do not print these platform settings.

The POC API is not an enterprise end-user authorization system. Network restriction
is not user authentication. Keep synthetic data only and privately scope access.
Any production adaptation needs approved user authentication, route-level
authorization, abuse controls and data handling.

## Data and application boundaries

- Synthetic neutral records only; no real names, emails, personal/financial/health
  data or production extracts.
- Parameterized SQL, input validation, stable pagination, constraints and
  explicit transaction boundaries.
- Bounded concurrency/pools, command/request timeouts, safe cancellation,
  retry budget, circuit breaker and idempotency for replay-safe writes.
- Inefficient queries and connection storms disabled by default; explicit
  unsafe-test gates and disposable-target checks.
- The canonical controlled client requires verified `poc_mode=true`,
  `poc_marker=sql-vcore`, `environment=poc` and current application/synthetic-data
  flags. A legacy `{poc:true}` response alone is rejected; application markers
  are not Azure ownership or database-content proof.
- No transactional or security-sensitive cache responses without a consistency
  and authorization design.
- Encryption at rest is a service capability; customer key/residency requirements
  remain TBD and are not automatically satisfied by this POC.

## Passwordless data access and optional control secret

No SQL password, registry admin credential, stored Azure client secret or
populated connection string belongs in source or examples. ACR admin stays off.
No Key Vault is deployed. Passwordless refers to SQL and supported Redis managed-identity
authentication; it is not a claim that every optional experiment is secretless.

The optional protected experiment-control interface uses a separate short-lived
private control token (`INTERNAL_API_TOKEN` on the API,
`POC_INTERNAL_API_TOKEN` for the runner). Local defaults have no token; the Azure
deployment orchestrator supplies one through encrypted Container Apps secret
references. It is not a SQL password. Enabling controlled maintenance/
cache/metrics operations requires approved secret delivery, scope/network review,
redaction and removal/rotation after the test. Never put its value in documentation,
shell history, deployment output or a public artifact. A future managed-identity
control-plane design should be reviewed independently rather than assuming this
POC bearer control is production end-user authentication.

The current control mechanism is an externally supplied high-entropy shared
bearer secret, checked with constant-time comparison, plus an allowlist applied
to the **actual TCP peer**. Forwarded headers are not trusted as the source-IP
authority. Server `INTERNAL_API_TOKEN` and runner `POC_INTERNAL_API_TOKEN` hold
the same secret. The application does not issue a token or configure/retrieve it
from a vault. Without a token, internal routes return forbidden; the synthetic
business API and health routes remain anonymous behind their network controls.

The Azure orchestrator generates a cryptographically random ephemeral token,
passes it as an ARM secure parameter, and wires encrypted Container Apps secrets
to both API and runner process environments. Redeployment rotates the shared
value on both sides. Its single-use parameter file is removed in a `finally`
cleanup path; verify filesystem permissions and check for remnants after an
abrupt process termination. This exception is not permission to persist tokens
in `.env`, ordinary configuration, shell arguments/history, repository content,
logs or evidence. Do not inspect or print the value. Verify deployed secret
references and private-network restrictions without exporting secret contents.

Use ignored local files/environment variables for deployment-specific values.
Never check in `.env`, token caches, local settings with values, certificates,
private keys, state, populated parameter files, deployment outputs or backups.
Real identifiers are not credentials, but this repository still forbids them in
public documentation/evidence. Use named angle placeholders or environment vars.

## Logging and evidence

Logs must redact credentials, tokens, headers, SQL parameter values, connection
configuration, real resource names, usernames and network addresses. SDK-generated
request/dependency telemetry can include URLs, IPs and SQL text: inspect exporter
configuration and sanitize artifacts even when application logs are structured.
Activity Log contains caller/claims metadata; project safe aggregate columns only.

Raw runs and local deployment configuration remain ignored/private. Sanitization
uses structured allowlisting plus value redaction and manual review; regex alone
does not recognize every customer name. Scan current worktree, staged content,
Git history and generated evidence. See [publication checklist](public-repo-checklist.md).

Cloud raw artifacts persist in private Blob Storage, under a nonpersonal run-ID
prefix, through Entra token authentication. Account/container settings and
managed-identity selection stay private. Storage private endpoints/DNS and scoped
RBAC are both necessary. Job logs contain persistence receipts, not raw payloads;
every upload failure fails the job rather than silently losing evidence.
Download only through an authorized private-network host into an ignored path,
validate hashes/inventory, and sanitize before sharing. Apply approved retention
and delete raw blobs only after preservation/review requirements are met.

## Deployment and destructive operations

CI validates only and does not deploy by default. Cloud workflows, if enabled,
require owner-configured protected environment, explicit approval, least-privilege
OIDC federation and no client secret. Owner-configured branch rulesets/review
requirements are not created automatically by repository files.

Scale, tier switch, failover, restore and destroy require explicit scoped
approval. Forced failover must retain destructive/data-loss flags and warning.
Cleanup scripts are for the approved dedicated POC scope only. Budgets, tags and
alerts provide guardrails, not guaranteed hard spending stops.

Use [SECURITY](../SECURITY.md) for private reporting and
[threat model](../threat-model.md) for design risks and residual gaps.

References: [Entra SQL authentication](https://learn.microsoft.com/azure/azure-sql/database/authentication-aad-overview),
[Azure Identity](https://learn.microsoft.com/python/api/overview/azure/identity-readme),
[SQL private endpoints](https://learn.microsoft.com/azure/azure-sql/database/private-endpoint-overview),
[GitHub Actions OIDC on Azure](https://learn.microsoft.com/azure/developer/github/connect-from-azure-openid-connect).
