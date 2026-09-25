# Architecture and scope

This repository is a reproducible evaluation harness, not an approved production
architecture. Every starting configuration is a **POC assumption, not a confirmed
customer requirement.** Customer objectives remain **TBD** in the
[workshop](customer-workshop.md). Live capacity, cost savings, scaling behavior,
availability, and disaster recovery: **Not demonstrated by this POC run.**

## Design

| Component | Design and purpose | Important boundary |
| --- | --- | --- |
| API | Python 3.12, FastAPI, Pydantic; REST and generated OpenAPI | No business-user UI; production end-user authentication requires a separate design |
| Database access | SQLAlchemy, pyodbc, Microsoft ODBC Driver 18, TLS certificate validation | Microsoft Entra access tokens from DefaultAzureCredential; no SQL password |
| Hosting | Container Apps Consumption, 0.5 CPU / 1 GiB, one replica for stable comparisons | Holding one replica is an experiment control, not a production scaling recommendation |
| Image registry | Azure Container Registry Basic, public authenticated endpoint, anonymous access/admin account disabled | Managed identities pull images; a private registry endpoint requires a separately costed Premium design |
| Baseline database | Azure SQL Database General Purpose, standard-series Gen5, provisioned 2 vCores | 5-GB cap, Local backup redundancy and seven-day short-term retention are POC assumptions; neither Managed Instance nor SQL on a VM |
| Secure network | Internal Container Apps environment, private app ingress, SQL private endpoint, private DNS, SQL public access off | A workstation needs approved VNet connectivity and DNS; cloud identity alone does not supply network access |
| Bootstrap | Separate managed identity, configured as SQL Microsoft Entra-only administrator; initialization job | Performs migrations, deterministic seed, and contained runtime-user grants; elevated access is not runtime access |
| Runtime | Separate managed identity with least-privilege contained database permissions | No schema modification, database ownership, or platform-management rights needed for normal requests |
| Workload | Separate runner job or VNet-connected local Locust process | Load generation must not share the measured API process |
| Durable evidence | Private Azure Blob account/container with private endpoint/DNS; runner identity has scoped Storage Blob Data Contributor | Full raw files; 21-day lifecycle plus seven-day soft delete are POC assumptions; no storage keys, SAS or public blob access |
| Observability | Application Insights, Log Analytics, MI REST SQL configuration/metrics/logs plus post-workload Query Store/SQL observer | No CLI inside cloud job; separate contained CONNECT/VIEW DATABASE STATE grants, no app-table/admin rights; fresh Online gate and no observer SQL in idle windows |
| Caching | Disabled by default; development memory cache; optional Redis compatibility | No paid cache deployed by default; see [cache decisions](workload-guide.md#cache-comparison) |

See the eight [architecture diagrams](architecture-diagram.md) and
[ADRs](adr/README.md).

## Request and failure path

The API validates inputs, applies bounded admission/concurrency controls, checks
eligible caches, and acquires a bounded database connection. Parameterized SQL
runs with command timeouts and explicit transaction boundaries. Retry decisions
are limited by error classification, request deadline, maximum attempts, retry
budget, and circuit state. A transactional operation uses an idempotency key
where supported; an uncertain write must not be blindly repeated.

Transient failures can produce delay, retry, rejection, or timeout. There is no
single universal overload outcome. The [outcome guide](spike-and-throttling-guide.md)
defines what evidence distinguishes these cases.

`/healthz` is a process-only health check. Readiness is an explicit database
connectivity check; it can resume a paused database or keep serverless active.
Do not use SQL readiness as a recurring liveness probe in the idle experiment.
Retries do not replace capacity planning, network design, or correct permissions.

## Controlled comparison

Use the **same database**, schema, data, region, hardware family, storage,
application image, one-replica app settings, monitoring, workload file, random
seed, warm-up, and measurement duration:

1. Profile A: provisioned 2 vCores.
2. Profile B: scale that database to 4 vCores; capture the operation and client
   behavior; return to the original configuration.
3. Profile C1: switch the same database to supported General Purpose serverless,
   suggested minimum 0.5 / maximum 4 vCores, auto-pause disabled.
4. Profile C2: enable a supported auto-pause delay; run a separate genuine idle
   and resume experiment; restore the baseline afterward.

The selected region's current capabilities must validate exact combinations.
Do not silently substitute hardware, compute bounds, backup settings, or zone
redundancy. Record any approved substitution as a comparison limitation.
Serverless is a **compute tier** in the vCore model, not burst-credit capacity,
unlimited capacity, or a promise of immediate scaling.

## Security profiles

The default customer-secure profile has private connectivity and passwordless
SQL managed-identity authentication. The explicitly gated evaluation profile
temporarily enables only the
operator's exact caller IPv4 SQL firewall entry and matching API IP restriction.
It must not enable an all-address rule, a broad CIDR, or “Allow Azure services.”
Remove temporary rules and verify public access is off after evaluation.

SQL, API ingress and raw evidence use the private design; this is not an
all-services-private-endpoint architecture. ACR Basic uses its authenticated
public endpoint with anonymous/admin access disabled. Application Insights uses
its public SDK ingestion endpoint; that does not make stored telemetry publicly
readable or expose SQL. Review these egress boundaries against customer policy.

No Key Vault is deployed. The deployment orchestrator generates a cryptographic
ephemeral control token and supplies an ARM secure parameter to encrypted
Container Apps secret references shared by API and runner. Redeployment rotates
both. The app itself does not issue/fetch that token, and the full deployment is
not entirely secretless. See
[control authentication](security-guide.md#passwordless-data-access-and-optional-control-secret).

## HA, DR, and optional extensions

Built-in in-region availability and supported zone redundancy are distinct from
cross-region DR. Optional failover groups use asynchronous geo-replication:
one writable primary, potentially readable secondary, read-write and read-only
listeners. The default failover policy is manual. Application active/active
hosting does not make Azure SQL multiwrite. DR also needs application, identity,
network, DNS, and operational recovery; RTO/RPO remain TBD.
The optional module provisions a real secondary SQL server/database and a Manual
failover group, but it is **SQL-only DR**. The application remains regional; no
second-region application failover is provisioned or demonstrated.

Business Critical is opt-in only after measured I/O/latency or replica requirements
justify its cost. `enable_business_critical` defaults false and permits only a
capability-validated provisioned extension; the standard test matrix stays GP-only.
Hyperscale is not deployed for a sub-5-GB POC; consider it only
if data growth, read scale, restore, or architecture requirements materially change.

`enable_legacy_redis=false` keeps the private Standard C1 Redis 6 compatibility
module off; enabling it requires eligibility/cost approval and runtime Entra
data-access configuration, not access keys. New cache designs should prefer
Azure Managed Redis. `enable_sql_diagnostics=false` keeps selected SQL diagnostic
log/metric export opt-in; native platform metric availability is a separate
control. These defaults are a **POC assumption, not a confirmed customer requirement.**

## Evidence boundary

Cloud runner jobs persist **all raw run files**, including required manifest and
report artifacts, to private Blob Storage under the run-ID prefix. Storage
account/container environment variables enable mandatory upload; any upload
failure must fail the job rather than report successful evidence persistence.
Local runs without storage settings continue to persist files normally.

`POC_EVIDENCE` logs contain artifact file/hash/byte/prefix receipts only, with no
raw or sanitized artifact payloads. `POC_EVIDENCE_UPLOAD` records completion with
prefix and full completion-manifest hash/count.
The completion manifest holds the complete file inventory and per-file hashes.
Before emitting completion, the job reads back every blob and the archive
manifest and checks actual lengths/SHA-256. Verified deployment smoke also
requires matching exact-execution/profile evidence, SQL business-request success
and required collection. Its job-side archive proof leaves independent operator
download false.
Logs are not the durable artifact store. An authorized VNet-connected operator downloads the private files,
verifies inventory/hashes, then sanitizes and reviews a separate public bundle.
Raw local outputs and `deployment.local.json` are ignored and private. Platform
metrics, Query Store, activity, errors and pricing still require actual collection;
durable storage does not turn missing observations into measurements.
See [evidence procedure](evidence-guide.md).

## Official references

- [Azure SQL vCore model](https://learn.microsoft.com/azure/azure-sql/database/service-tiers-vcore)
- [Serverless overview](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-overview)
- [Microsoft Entra authentication](https://learn.microsoft.com/azure/azure-sql/database/authentication-aad-overview)
- [Private endpoints](https://learn.microsoft.com/azure/azure-sql/database/private-endpoint-overview)
- [Container Apps networking](https://learn.microsoft.com/azure/container-apps/networking)
- [Availability](https://learn.microsoft.com/azure/azure-sql/database/high-availability-sla-local-zone-redundancy)
- [Failover groups](https://learn.microsoft.com/azure/azure-sql/database/failover-group-sql-db)
