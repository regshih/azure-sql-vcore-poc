# Deployment and restoration guide

Read [security](security-guide.md), [assumptions](assumptions.md), and
[cost](cost-guide.md) first. This guide does not authorize a deployment. Every
capacity default is a **POC assumption, not a confirmed customer requirement.**
Azure deployment and end-to-end managed-identity validation:
**Not demonstrated by this POC run.**

## Prerequisites and local configuration

1. Use a dedicated, disposable POC scope with an approved budget and cleanup
   owner. Confirm the intended authenticated cloud account privately; never paste
   account output, identifiers, local profile paths, or deployment output in Git.
2. Install Python 3.12, Azure CLI, Bicep, Git, a supported shell, and Microsoft ODBC
   Driver 18. Docker is needed when building an image locally. Review the actual
   dependency manifest and bootstrap wrapper before executing it.
3. Confirm operator permissions for deployment, identity assignments, networking,
   image build/push, SQL Entra administration, diagnostics, and jobs. Runtime
   identity must not inherit deployment privileges.
4. Select an approved region and validate the exact SQL hardware, provisioned
   capacity, serverless bounds/delay, zone redundancy, and backup combinations.
   Region, network ranges, identities, budget, and objectives are customer **TBD**.
5. Copy [deployment.example.json](../deployment.example.json) to an **ignored
   local file**, such as `deployment.local.json`, using the operations CLI
   configuration contract. The wrapper generates the required Bicep parameters.
   Supply only real local values privately. Do not
   commit a populated `.env`, Bicep parameter file, or deployment output.
6. Inspect `--help` before running wrappers. Shell wrappers forward their
   arguments; they are not a substitute for missing prerequisites or approvals.

PowerShell commands below run from the repository root. Replace named angle
placeholders **locally**; do not paste placeholders literally into executable
configuration. Bash counterparts use the same wrapper names with `.sh`.
Direct Python modules are preferred below: PowerShell AST validation does not
prove `.ps1` execution is allowed, and organizational execution policy may block
wrappers. Do not weaken or bypass that policy. The wrappers remain optional
argument-forwarding conveniences where execution is permitted.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m src.operations.cli --help
.\.venv\Scripts\python.exe -m src.operations.cli deploy --help
```

The first command must resolve to the selected Python 3.12 interpreter.
`bootstrap.ps1` is **not** a local dependency installer: it reruns the remote
SQL initialization job after deployment and requires local config and POC
confirmation.

```powershell
Copy-Item .\deployment.example.json .\deployment.local.json
```

Edit only that ignored local copy. The published example deliberately cannot pass
deployment-value validation until its placeholders are replaced privately.
Placeholder-only Bicep parameter examples are also available for
[secure](../infra/bicep/parameters/secure.example.bicepparam) and
[evaluation](../infra/bicep/parameters/evaluation.example.bicepparam) profiles.
Do not populate the tracked examples with customer values; use the approved
ignored local configuration workflow.

Run the project's lint, type, unit, integration, Bicep, shell syntax, and publication
checks documented in [CONTRIBUTING](../CONTRIBUTING.md). Local tests do not prove
Azure permissions, private DNS, SQL transaction semantics, or cloud provisioning.

## Customer-secure deployment: default

The secure profile creates private SQL connectivity with private DNS, disables SQL
public access, and uses an internal Container Apps environment and private app
ingress. A local evaluation client must resolve and reach the private services
it uses via an approved VNet-connected host, VPN, or equivalent authorized
network. Alternatively, submit performance profiles to the private runner job
through the management plane using the
[cloud execution contract](workload-guide.md#private-cloud-execution-contract).
This does not require the operator workstation to reach the API directly; private
artifact download remains a separate network and permission requirement.
Do not open public access to compensate for a workstation without connectivity.

Deployment is staged: infrastructure and identities; application image; SQL
initialization job; runtime application and workload job. The initialization job
uses the separate bootstrap managed identity configured as SQL Entra-only
administrator to apply migrations, seed, and create/grant the runtime contained
user. Inspect init-job completion before trusting an app readiness response.

```powershell
.\.venv\Scripts\python.exe -m src.operations.cli deploy --config <local-config-path> --confirm-poc
```

For a read-only preflight inspect `capabilities` and the deployment what-if path:

```powershell
.\.venv\Scripts\python.exe -m src.operations.cli capabilities --config <local-config-path>
.\.venv\Scripts\python.exe -m src.operations.cli deploy --config <local-config-path> --what-if-only
```

These can contact Azure and write private ignored preflight evidence; they are not
a deployment approval. The what-if path does not prove runtime connectivity.
An `Unsupported` what-if classification is unresolved preview coverage, not a
no-op or a validated live resource. Review dynamic role/DNS changes and all
other unsupported entries before execution; a successful preview creates
neither resources nor performance evidence.

### Local configuration contract

The operations CLI accepts an **ignored JSON file** and rejects unknown keys.
Do not point it at a public example file. A minimal starting shape for the secure
provisioned baseline is shown below; replace placeholders only in the private
copy. It is deliberately not executable as published.

```json
{
  "subscription_id": "<subscription-id>",
  "resource_group": "<resource-group-name>",
  "environment_name": "<environment-name>",
  "region": "<azure-region>",
  "deployment_profile": "secure",
  "allow_evaluation_public_access": false,
  "evaluation_ip": "",
  "sql_compute_tier": "Provisioned",
  "sql_vcores": 2,
  "sql_min_vcores": 0.5,
  "sql_auto_pause_delay": -1,
  "sql_max_size_gb": 5,
  "sql_zone_redundant": false,
  "sql_backup_redundancy": "Local",
  "enable_dr": false,
  "enable_business_critical": false,
  "enable_legacy_redis": false,
  "enable_sql_diagnostics": false
}
```

Defaults in this JSON are a **POC assumption, not a confirmed customer
requirement.** Naming constraints are validated by `DeploymentConfig`: use an
approved resource-group name with the required prefix and an environment label
that meets its length/character rules. Do not copy an actual naming convention
into public examples.

| Private input | Operator action |
| --- | --- |
| Subscription, scope, environment label, region | Supply approved values locally; confirm current account and budget |
| Secure/evaluation mode | Secure by default; evaluation needs explicit flag and exact public caller IPv4, not CIDR |
| SQL capacity/storage/backup/zone | Validate exact region capabilities and approved POC settings |
| Optional DR | `enable_dr` plus explicit distinct `secondary_location`; additional cost and pause incompatibility review |
| Deployment outputs | CLI updates local SQL/app/job/registry/identity/workspace/listener fields; never publish the populated file |
| Protected experiment controls | Deployment generates the token and injects encrypted app/runner secret references; no token in the deployment JSON example |

The standard wrapper comparison limits provisioned capacity to 2/4 and
serverless maximum to 4. A higher maximum or other service-tier extension requires
a reviewed implementation/configuration change, capability validation and new
cost approval; it is not an undocumented CLI switch.

### Explicit optional extensions

| Local configuration key | Default / scope | Required review |
| --- | --- | --- |
| `enable_business_critical` | `false`; provisioned-only Business Critical extension | Validate actual regional BC capability, approved requirement/cost and a separate experiment; the standard matrix remains GP-only |
| `enable_legacy_redis` | `false`; private Standard C1 Redis 6 compatibility resource | Verify current customer creation eligibility/retirement, private endpoint and runtime Entra data-access policy; no access keys |
| `enable_sql_diagnostics` | `false`; selected SQL diagnostic log/metric export | Review supported Errors/Timeouts/Blocks/Deadlocks categories, ingestion cost, retention and actual workspace schema |
| `enable_alerts` | `false`; metric/activity rules disabled, three log-alert resources omitted; all 14 definitions retained in source with conditional serverless rule | Requires actual required tables ingested, private `alert_action_group_ids`, non-TBD `alert_owner`, HTTPS `alert_runbook_base_url`, verified queries and noise/routing review |

These extension defaults and cache size/version choices are a **POC assumption,
not a confirmed customer requirement.** Enabling a configuration flag does not
replace operation-specific approval. Prefer Azure Managed Redis for new cache
designs; this compatibility flag is not an automatic Managed Redis deployment.
No optional extension deployment or effectiveness is asserted by this guide.
Use `alert_thresholds` only with the supported keys in the
[alerting guide](alerting-guide.md#threshold-configuration-keys). Defaults are
starting assumptions, not customer SLOs; skipped query validation is not proof
that ingestion or paging works. Disabled scheduled-query resources can still
execute/validate queries during creation despite `skipQueryValidation=true`.
Their resource creation is therefore opt-in, not merely their paging state.

Verify privately:

- SQL has public access disabled and Entra-only authentication.
- Private endpoint is approved; private DNS resolves correctly from the app,
  init job, runner, and chosen operator host.
- ACR admin is off; image pull uses identity.
- Initialization completed, and runtime SQL rights are restricted to API needs.
- Process health succeeds; run one explicit readiness check and smoke workload.
- Telemetry reaches the selected workspace with run/version metadata.
- Runner-managed identity can persist the full raw artifact inventory to the
  private Blob container; verify the upload receipt/hashes, not only job logs.
- The selected execution image satisfies each requested workflow: the baseline
  Python image has no Azure CLI. HTTP workloads, MI REST/read-only SQL-observer
  collection and SDK Blob persistence do not need it. An operator using Azure
  CLI credentials, matrix and management-plane idle paths still need an
  authorized CLI-equipped environment; missing tools are not complete telemetry.
- Runner monitoring environment uses `SQL_RESOURCE_ID` for the database ARM ID,
  `AZURE_SUBSCRIPTION_ID`, `LOG_ANALYTICS_WORKSPACE_ID` for the workspace customer
  GUID, and `AZURE_CLIENT_ID` for the runner identity client GUID. Verify SQL
  resource Reader and workspace Log Analytics Reader grants separately from
  Blob data rights. The post-workload SQL observer also needs separately
  provisioned contained `CONNECT` and `VIEW DATABASE STATE`, ODBC 18 and private
  SQL connectivity. It has no application-table/schema/write/admin grants.
  See the [collector contract](evidence-guide.md#cli-free-cloud-monitoring-collector).
- Rebuild the approved image and apply current environment/role wiring before
  validating REST collection. Verify the deployed job image/revision rather
  than assuming source changes altered a previously deployed container.
- No identifiers or credentials were written to tracked files.

For a selected performance workload rather than the deployment's smoke profile,
use the [private cloud execution contract](workload-guide.md#private-cloud-execution-contract).
`src.experiments.cloud_job` submits a per-execution template through an authorized
Azure CLI without requiring workstation-to-private-API connectivity. It does not
mutate the persistent job template. Exact execution success and upload receipt
retrieval must be followed by independent private Blob download/hash verification.

### Verified deployment smoke

Deployment and the explicit smoke operation share `launch_smoke`. It waits for
the exact submitted execution and requires SQL-backed business-request success,
matching smoke profile/run evidence, successful required collection and
managed-identity readback SHA-256/length verification of every raw blob plus
the completion archive manifest. A completed job or receipt alone is insufficient.

```powershell
.\.venv\Scripts\python.exe -m src.operations.cli smoke --config <local-config-path> --confirm-poc
```

The private `smoke-verification.json` distinguishes
`archive_verification=runner-readback-confirmed` from
`operator_blob_download_verified=false`. Job-side verification is not independent
operator download. Preserve that distinction until the separate private retrieval
workflow succeeds. The Python helper accepts an optional duration; do not invent
a `--duration` switch for the operations smoke CLI.
Live SQL-backed verified smoke: **Not demonstrated by this POC run.**

To rerun the initialization job after reviewing migration/seed replay behavior:

```powershell
.\.venv\Scripts\python.exe -m src.operations.cli bootstrap --config <local-config-path> --confirm-poc
```

## Evaluation profile: temporary exposure

Evaluation is explicit opt-in, not the default fallback. Approve the temporary
exposure, use the exact caller IPv4 for the SQL firewall and app IP restriction,
and never broaden it to an all-address rule or Azure-services bypass. Configure
the evaluation gate in the local parameter/configuration file; preserve all other
token/TLS/least-privilege controls.

An IPv4 allowance does not authenticate end users. Do not expose synthetic test
APIs as a production service. If the caller address changes, stop and review the
new exact address. After testing, remove rules, disable public access, verify
denial from outside the approved network, and use the secure profile thereafter.

## Local API and database administration

Use an identity with explicitly granted SQL rights and an approved network path.
Use environment variables following `.env.example` and the settings reference;
the application does **not** automatically load `.env`. Local defaults use an
in-memory backend, which is only for development/tests and does not validate SQL.
To target real POC SQL, set the following placeholders locally using approved
identity and private connectivity; do not print tokens or connection configuration.

```powershell
$env:REPOSITORY_BACKEND = "sql"
$env:SQL_SERVER = "<sql-server-hostname>"
$env:SQL_DATABASE = "<database-name>"
.\.venv\Scripts\python.exe -m src.database.manage migrate
.\.venv\Scripts\python.exe -m src.database.manage bootstrap --runtime-object-id <runtime-principal-id>
.\.venv\Scripts\python.exe -m src.database.manage seed --size small --seed 42
.\.venv\Scripts\python.exe -m src.api
```

The local API entry point binds to loopback by default. Production uses the
`src.api.app:create_app` factory with Gunicorn and `uvicorn_worker`, one worker for
controlled comparisons. Do not run a development server as the deployed service.
The seed generator uses synthetic records; verify final storage remains below
the 5-GB cap before selecting a larger dataset.

### Optional local control-token setup

The local application has no default token. For an approved
local synthetic experiment, the following generates a secret only in the current
PowerShell process environment without printing it:

```powershell
$bytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
$env:INTERNAL_API_TOKEN = [Convert]::ToBase64String($bytes)
$env:POC_INTERNAL_API_TOKEN = $env:INTERNAL_API_TOKEN
$rng.Dispose()
```

Launch API and runner as children of this same process so both inherit the
matching environment; unrelated terminal sessions do not inherit it. Do not
print, write to a file, interpolate into command arguments or paste the value.
Keep the approved actual-peer network allowlist and required POC/unsafe flags.
Remove the environment variables and terminate the test processes afterward.

This local setup is not the Azure delivery path. The deployment orchestrator
generates an ephemeral cryptographic token, passes it through an ARM secure
parameter and shares encrypted Container Apps secret references between API and
runner. Its single-use parameter file is removed in `finally`; no token value is
printed, committed or retained in ordinary local configuration. Redeployment
rotates both sides. Verify references and post-failure file cleanup without
printing secrets. The core application does not issue or fetch the token itself.

## Provisioned scale comparison

Export the original configuration privately before changing capacity. Do not
assume the original is 2 vCores if an operator already changed it.

```powershell
.\.venv\Scripts\python.exe -m src.operations.cli scale --config <local-config-path> --vcores 4 --confirm-poc
```

Record operation start/end UTC and continuous client outcomes during scaling.
Wait for control-plane completion, reconnect, confirm the service objective, warm
consistently, then rerun identical peak/spike workloads. Restore original capacity
using the same command with the recorded original value; capture restoration.
Scaling is neither guaranteed instantaneous nor invisible to clients.

## Serverless comparison and baseline restoration

Switch the **same database**, after exact capabilities validation:

```powershell
.\.venv\Scripts\python.exe -m src.operations.cli switch-compute-tier --config <local-config-path> --compute-tier Serverless --min-vcores 0.5 --max-vcores 4 --auto-pause-delay -1 --confirm-poc
```

C1 disables auto-pause. For C2, substitute the approved currently supported pause
delay; current guidance permits a minimum of 15 minutes, but deployment must
validate the actual capabilities. Follow [serverless testing](serverless-test-guide.md)
rather than assuming a short sleep demonstrates pause.

After C2, use `switch-compute-tier --help` to restore the recorded provisioned
configuration and verify it. For an original provisioned 2-vCore baseline:

```powershell
.\.venv\Scripts\python.exe -m src.operations.cli switch-compute-tier --config <local-config-path> --compute-tier Provisioned --vcores 2 --confirm-poc
```

Use the **recorded original** capacity instead if different. Restore every other changed setting: tuning, cache,
unsafe-test features, network exposure, replica configuration, and diagnostic
pollers. The manifest must show both requested and observed configurations.
The matrix and slow-query comparison enforce a narrower automatic restoration
envelope: original GP Gen5 2/4-vCore SKUs with known serverless minimum/pause
when applicable. They reject unsupported/unknown originals before mutations.
After cleanup they verify full SKU, maximum size, zone/read scale, license and
backup redundancy, not capacity alone. See
[original-state guards](test-matrix.md#original-settings-and-restoration).

## Evidence and cleanup

Cloud runner jobs upload all raw files to the configured private Blob container.
The runner receives `EVIDENCE_STORAGE_ACCOUNT`, `EVIDENCE_STORAGE_CONTAINER`
and its managed-identity selection through `AZURE_CLIENT_ID`; outputs populate
the private deployment configuration. Storage access uses Entra tokens, no keys.
The runner identity needs scoped Storage Blob Data Contributor and private
endpoint/DNS reachability. Upload failure must produce a nonzero job result,
not successful completion.

Current POC defaults are Local SQL backup redundancy with seven-day short-term
retention and a 5-GB cap; raw Blob lifecycle deletion after 21 days with seven-day
soft delete. Each is a **POC assumption, not a confirmed customer requirement.**
Soft-deleted data can remain billable after lifecycle deletion; preserve approved
evidence and review actual retention/cost before cleanup.

Retrieve the `POC_EVIDENCE_UPLOAD` prefix/full-manifest-hash receipt and use an authorized
VNet-connected host to download the full artifacts. A client outside the private
network cannot download merely because it has an Azure role. Grant the operator
the minimum approved blob read role separately; do not broaden the network or
borrow the runner's write identity. Follow [evidence collection](evidence-guide.md)
and verify complete persistence before deleting jobs/resources. A durable bundle
still must explicitly mark metrics that were never collected.

```powershell
.\.venv\Scripts\python.exe -m src.experiments.storage --run-id <run-id-from-receipt> --output <new-ignored-download-directory> --manifest-sha256 <full-manifest-sha256> --config <local-config-path> --credential azure-cli
```

The command verifies `archive-manifest.json` against the receipt and then checks
every file's path, length and SHA-256. Preserve only verified downloads. The
download accepts `--output` (alias of `--run-dir`) as its new destination; it must
not already exist. Exact `--download-prefix` is an alternative to `--run-id`,
not a second simultaneous selector. `POC_EVIDENCE` contains file/hash receipts
only—no raw or sanitized artifact payloads.
Automatic job-side blob readback verification occurs before the completion receipt;
this independent operator download remains a separate verification boundary.

Before deleting, confirm the exact disposable scope and preserve verified full
raw evidence under the approved private retention policy, with reviewed
shareable copies kept separately. Do not discard original private artifacts
merely to clear the publication scanner. Inspect the destruction command's help
and retain its required confirmation/destructive gates:

```powershell
.\.venv\Scripts\python.exe -m src.operations.cli destroy --config <local-config-path> --confirm-poc --allow-destructive-tests
```

Delete only POC resources, including optional replicas/cache, registry, private
evidence blobs/account, endpoints,
app environment, diagnostics workspaces, and approved restored test copies.
Check the control plane for completion and later billing records for residual
charges. Never issue a broad subscription cleanup.

For only a generated restore-validation copy, add
`--restore-database <restored-database-name>`; verify the generated destination
and required purpose/POC tags match the intended copy. Never use that parameter
to remove the original database.

## Troubleshooting without weakening controls

| Symptom | Check first |
| --- | --- |
| DNS or connection timeout | VNet reachability, private DNS link/resolution, endpoint approval, SQL port path |
| Token or login rejected | Selected local identity, token audience, SQL Entra admin initialization, contained user |
| Image pull failure | Registry role and assigned identity, image tag availability, registry network path |
| Init job fails | Migration ordering, explicit bootstrap identity, grants, replay safety, sanitized job error |
| Readiness fails but health passes | Database path, rights, timeout, serverless state; health is process-only |
| Unsupported SQL configuration | Current regional capabilities; fail explicitly rather than silent substitution |
| No metrics | Correct resource/window/destination, diagnostic categories, ingestion delay, table schema |
| `ManagedEnvironmentCapacityHeavyUsageError` | Regional Container Apps capacity; preserve the failed deployment's partial inventory/cost, review another region and new disposable scope only with explicit approval |
| Scheduled-query rule creation fails against missing tables | Actual ingestion/schema/query prerequisites; leave log-alert resource creation off rather than relying on disabled state or skipped validation |

A failed deployment is not automatically rolled back. SQL, storage, identities,
networking or registry resources may already exist and remain billable even
when Container Apps creation fails. Preserve private operation evidence and
inventory every original and replacement scope. A separately approved regional
retry must not overwrite the original configuration or imply the first resources
were deleted. Track budget, owner and explicit cleanup separately for each.
Region changes require fresh capability/cost/network review and do not create a
fair cross-region performance comparison.

Product behavior references: [private endpoints](https://learn.microsoft.com/azure/azure-sql/database/private-endpoint-overview),
[Entra authentication](https://learn.microsoft.com/azure/azure-sql/database/authentication-aad-overview),
[serverless](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-overview).
