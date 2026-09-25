# Workloads and controlled comparisons

All default rates, duration, concurrency, cache lifetime, and data size are a
**POC assumption, not a confirmed customer requirement.** Customer peak, latency
objectives, staleness tolerance, and workload representativeness are **TBD**.
Capacity at 10 or 100 users: **Not demonstrated by this POC run.**

## Volume is not concurrency

50,000 reads/day equals approximately **0.579 reads/second** over 24 hours or
**1.736 reads/second** over eight hours. These are average volume conversions,
not peak API rates or a database sizing rule. One REST request may issue several
SQL statements, while a cache hit may issue none. Record logical read operations,
HTTP requests, SQL calls, SQL statements, and rows/IO separately.

An accelerated run must record the source time horizon, run duration, acceleration
factor, read/write mix, target arrival rate, achieved rate, user limit, spawn rate,
and equivalent-volume calculation in its manifest. For an eight-hour source
pattern compressed into a shorter run, acceleration is source seconds divided
by measured workload seconds. Check whether the profile's rate already includes
acceleration before overriding it; do not multiply twice.

Compression changes concurrency, cache expiration, memory residency, background
work, scale responsiveness, and idle time. It does not reproduce a whole
production day. Closed-loop clients may achieve fewer requests when latency rises:
report achieved throughput and omitted arrivals instead of assuming configured
rate was delivered.

## Profile catalog

Files live in `load-tests\profiles`; inspect each version-controlled profile and
the runner's `--help` before executing. Every profile must run against a confirmed
disposable POC target.

| Profile | Purpose and required phases | Interpretation limit |
| --- | --- | --- |
| `smoke` | Low-rate connectivity, schema, API, telemetry, collector validation | Not a capacity test |
| `expected` | Accelerated approximate daily read volume plus small writes | Read mix and acceleration must be explicit |
| `business-hours` | Morning ramp, steady use, midday peak, decline | Idle-cost claims require a separate genuine idle window |
| `peak` | Higher rate/concurrency held for stabilization | Peak is a POC assumption until approved |
| `spike-1-minute` | Baseline, fast ramp, one-minute spike, recovery | Short platform sampling can obscure short peaks |
| `spike-5-minute` / `spike-15-minute` | Same shape with sustained spike duration | Keep the same profile across compute configurations |
| `variable-demand` | Low, moderate, high, low, idle/near-idle cycles | Near-idle is not sufficient to guarantee auto-pause |
| `idle-resume` | C2 only: warm, disconnect, observe pause, timed first request, stream | Disable SQL polling and dispose pools during idle |
| `connection-storm` | Bounded deliberately poor reuse versus correct pooling | Requires unsafe-test opt-in; never arbitrary production targets |
| `slow-query` | Controlled inefficient query versus tuned query/index | Requires unsafe-test opt-in and low initial rate |
| `cache-comparison` | No cache versus development cache or approved optional Redis | Observe stale reads, not just hit ratio |
| `failover` | Continuous low-rate operations with approved role transition | Stable client recovery differs from operation completion |

## Running

Choose the execution location explicitly:

- **Local runner:** the invoking host must have approved private connectivity to
  the API. The commands below use this mode.
- **Private Container Apps job:** an authorized workstation submits the workload
  through the Azure management plane; the existing VNet-connected runner job
  calls the private API. This avoids opening the API or requiring the workstation
  to route directly to it. Select the requested performance profile and overrides;
  rerunning the deployment's default smoke job does not run that performance test.

Example commands contain only placeholders:

```powershell
.\.venv\Scripts\python.exe -m src.experiments.runner --profile smoke --host <base-url> --product-count <observed-product-count>
.\.venv\Scripts\python.exe -m src.experiments.runner --profile expected --host <base-url> --product-count <observed-product-count> --observe-dataset-state
.\.venv\Scripts\python.exe -m src.experiments.runner --profile peak --host <base-url> --product-count <observed-product-count> --observe-dataset-state
.\.venv\Scripts\python.exe -m src.experiments.runner --profile spike-1-minute --host <base-url> --product-count <observed-product-count> --observe-dataset-state
.\.venv\Scripts\python.exe -m src.experiments.runner --profile variable-demand --host <base-url> --product-count <observed-product-count> --observe-dataset-state
```

The direct runner is `python -m src.experiments.runner`. Its configurable controls
include `--users`, `--spawn-rate`, `--rate`, `--duration` (seconds), and `--output`.
`--host` is an origin only: no path, query or embedded credentials.
`--write-ratio` and `--product-count` also change the workload and belong in the
manifest; keep output overrides inside an ignored private results directory.
Record every override. Do not change workload rate merely because a larger
database can complete more requests. Use the same workload file hash and compare
both attempted and completed work.

### Verified SQL metadata and product distribution

Before SQL comparisons, require an explicit fresh protected metadata snapshot
with **both** `repository_backend=sql` and `sql_adapter_configured=true`,
schema/dataset versions, `tuning_mode` and
`dataset_size={product_count,work_item_count,counts_source}`. SQL matrix,
tuning/cache comparisons require these checks before control mutations.
Controlled, configured and cloud runs also reject memory or unverified SQL adapters.
Ordinary local smoke
can illustrate a memory backend, but is not SQL or capacity evidence.

For product-ID workloads, pass the **actual observed seeded product count**
explicitly as `--product-count`
and keep it identical across compared profiles. Current generator presets have
24 products for small, 2,000 for medium and 50,000 for large:
**POC assumption, not a confirmed customer requirement.** Verify the fresh
snapshot rather than relying solely on that preset table. A distribution that
exceeds the observed product count fails with `--product-count` guidance; the
runner must never silently clamp it or change the profile/hash.
Department-only slow-query and connection-storm diagnostics use no product IDs
and are exempt from this product-distribution bound, not from SQL-adapter,
authentication or unsafe-test guards.

Preserve the ordered boundaries: fresh metadata → baseline counters → workload →
end counters → fresh metadata. No metadata refresh belongs inside the measured
window or idle interval. Counter snapshots still require matching process
instances, and excluded metadata SELECTs can still warm SQL caches.

For operator-side configuration/metric enrichment, supply
`--config <local-config-path>` and `--collect-cloud`. The managed cloud job uses
the [CLI-free REST collector](evidence-guide.md#cli-free-cloud-monitoring-collector)
automatically instead. Its required-source failure is nonzero and recorded,
not silently inferred from a profile name.

### Private cloud execution contract

The implemented management-plane launcher is `src.experiments.cloud_job`.
Run it on an authorized Azure-CLI-equipped workstation with ignored deployment
configuration. The workstation does not need network access to the private API.
Replace all angle placeholders before running:

```powershell
.\.venv\Scripts\python.exe -m src.experiments.cloud_job --help
.\.venv\Scripts\python.exe -m src.experiments.cloud_job --config <local-config-path> --profile expected --duration <duration-seconds> --users <concurrent-users> --rate <requests-per-second> --product-count <observed-product-count> --confirm-poc --output results\local-untracked-runs\<launch-id>
```

Optional controls include `--spawn-rate`, `--write-ratio`,
`--wait-timeout` and `--poll-interval`. Output must be a new or empty directory
under `results\local-untracked-runs`. Wait timeout defaults to 14,400 seconds and
poll interval to 10 seconds: **POC assumption, not a confirmed customer requirement.**
Record overrides and achieved load; chosen users/rate are not customer capacity
requirements or evidence of SQL reads per second.
The command explicitly supplies `--product-count` from verified metadata;
do not reuse a larger bundled distribution against a smaller seeded dataset.

Before launch, the command checks the configured resource group, SQL target,
app and runner job for required POC tags, and checks the target application FQDN.
It requires a manual, single-replica, no-retry job with sufficient timeout
capacity. It snapshots the complete template privately, preserves container
names/images/resources/environment and init containers, and overrides only
runner command/arguments. It does not change the persistent job template.
Treat snapshots and execution logs as sensitive private evidence.

The launcher invokes `az containerapp job start --yaml` with the complete
execution template, using
[Jobs - Start, API 2025-01-01](https://learn.microsoft.com/en-us/rest/api/resource-manager/containerapps/jobs/start?view=rest-resource-manager-containerapps-2025-01-01).
An accepted start is not workload success. The command preserves the returned
execution identity, waits for **that exact execution**, ignores older successful
executions, and retrieves that execution's receipt logs.

After completion, retrieve its logs and full-artifact persistence receipt.
Require the requested workload metadata, a successful job result and complete
private persistence. Missing receipts, execution failure or timeout return
nonzero and record private failure evidence; the launcher does not automatically
restart. Do not assume a launcher timeout cancelled the remote job: inspect the
exact execution before approving any retry. A receipt observed in logs is not
independent download/hash verification. Use the
[private download and hash-verification workflow](evidence-guide.md#download-and-verification)
for raw files. Unlike management-plane job submission, downloading private Blob
contents still requires approved private connectivity.

Inside the job, the same module runs **without `--config`**, using `POC_HOST`,
`EVIDENCE_STORAGE_ACCOUNT` and `EVIDENCE_STORAGE_CONTAINER` from the preserved
environment and delegating to the ordinary runner. The job entry point remains
`src.experiments.cloud_job`; a smoke execution also needs explicit
`--product-count <observed-product-count>` in its approved arguments. Review
older profile-only job templates rather than assuming their distribution fits
the seed. Full private Blob persistence is mandatory in job mode; a missing destination or upload failure
is not success.
The launcher also requests `--collect-cloud --observe-dataset-state` automatically.
Required SQL-resource/workspace/identity environment settings must survive the
template override. Platform/log collection uses managed-identity REST without
Azure CLI; protected API dataset refresh is separate and occurs pre/post outside
the measured workload window. Cloud collection additionally performs bounded
post-workload Query Store/resource/storage observation after a fresh Online
control-plane check, using the same approved credential and `NullPool`.
Observer rights are separately provisioned: contained SQL `CONNECT` and
`VIEW DATABASE STATE`, never administrator or application-write access.
Idle/idle-after windows omit diagnostic SQL automatically; missing required
non-idle observer data makes collection incomplete, not successful telemetry.

The launcher accepts bundled profile names only, not arbitrary profile files.
It supports smoke, business-hours, expected, peak, spike, variable-demand and
failover-traffic workloads. Controlled cache, connection-storm and slow-query
profiles additionally require `--allow-unsafe-test` and all server-side guards;
`--confirm-poc` remains required. The launcher validates its configured target;
it is not an arbitrary-host runner or an authorization bypass. These workload
profiles do not themselves authorize a separate SQL failover operation.

The baseline image can run HTTP profiles, managed-identity REST monitoring and
SDK Blob persistence and read-only SQL-observer collection without Azure CLI,
but it does not contain `az`. Operator Azure CLI credentials, management-plane
idle controls and matrix still require an authorized CLI-equipped environment.
The launcher rejects
idle profiles before starting the baseline
job; use the explicitly approved CLI-equipped private operator path instead.
Do not assume arbitrary runner/matrix options are accepted by this launcher.
See the
[runtime-image limitation](evidence-guide.md#current-runtime-image-limitation).

Launcher implementation and local contract tests do not establish live execution,
private connectivity, workload success or independently verified persistence.
End-to-end cloud profile execution and artifact retrieval:
**Not demonstrated by this POC run.**

The dedicated deployment smoke gate also validates successful SQL business
requests, required collection and job-side readback hashes for every blob and
archive manifest. See [verified smoke](deployment-guide.md#verified-deployment-smoke).
That gate leaves independent operator download false until separately verified.

### Controlled internal endpoints

Cache, connection-storm, slow-query and idle/resume scenarios modify experimental
controls. Direct runner commands require `--allow-unsafe-test`, `--confirm-poc`, an explicit
`--allow-host <base-url>` for a remote HTTPS target, and the target's POC marker.
The application must explicitly enable unsafe testing where required.

The optional control interface also requires a transient private
`INTERNAL_API_TOKEN` configured on the API and the corresponding
`POC_INTERNAL_API_TOKEN` in the runner environment. These are **not** Azure SQL
credentials. Local defaults have no token; the Azure deployment orchestrator
generates the shared value and injects encrypted Container Apps secret references.
Use the approved private delivery mechanism for the controlled test,
never print them or put values in commands/source/evidence, and remove/rotate
them afterward. Do not weaken the control endpoint's network restriction.
An absent control token means protected snapshots or experiments cannot be
claimed as measured.

Both variables contain the same externally supplied high-entropy shared bearer
secret. The application neither issues nor retrieves it; deployment automation
handles generation/delivery and redeployment rotates both sides. The actual TCP peer is
checked against the source-network allowlist; forwarded headers are not trusted
to authorize callers. Passwordless SQL/Redis access does not make these optional
controls secretless. See [control authentication](security-guide.md#passwordless-data-access-and-optional-control-secret).

The API also applies its configured `INTERNAL_ALLOWED_NETWORKS` source-network
restriction. Mutating/unsafe controls require the server-side `POC_MODE=true`
marker and `ALLOW_UNSAFE_TESTS=true` where applicable; client confirmation flags
do not enable these server controls. Configure approved network values privately,
not in published examples.

| Protected endpoint | Contract and experiment use |
| --- | --- |
| `GET /internal/metadata` | Process-only metadata; explicit `refresh_database=true` pre/post snapshots validate SQL counts/version/tuning outside measured/idle intervals |
| `GET /internal/metrics` | Cumulative process-lifetime counters with `instance_id` and timestamp; collect isolated baseline/end snapshots |
| `POST /api/diagnostics/query` | Controlled body includes `allow_unsafe_test:true`, a synthetic department, bounded `delay_seconds` from 0 to 30, and `poor_pooling`; bearer/network/POC/unsafe gates remain required |
| `POST /internal/maintenance` | Confirmed `idle` drains/disposes pools, suspends database readiness and rejects API work until confirmed `resume` |
| `POST /admin/pool/dispose` | Confirmed pool-disposal alias with both server flags and bearer/network controls |
| `GET /internal/config` | Returns per-process instance/version and cache enabled/backend/TTL configuration |
| `PUT /internal/config` | Confirmed cache-enable change with `expected_version`; returns `previous` and `current`; restore the previous enabled state using the returned current version |

These controls are **per process**. Use the fixed single worker/replica and verify
`instance_id` across snapshots and mutations. A restart or unexpected instance
invalidates a naive before/after delta. Refreshing database metadata issues SQL:
do it before baseline capture or after end counters, never during the measured
window or C2 idle interval.

Cache controls cannot dynamically provision a backend. Configure an approved
`memory` or `redis` backend first; a disabled backend cannot be created by toggling
`cache_enabled`. Preserve backend/TTL and optimistic-version checks during
restoration. Retry, budget and circuit settings are currently environment-only;
there are no dynamic retry-storm configuration switches.

Select the backend at process startup through `CACHE_BACKEND`: `memory` only for
the allowed local/development comparison, or approved `redis` for a cloud
distributed-cache comparison. Runtime controls enable/disable that selected
backend; they do not switch providers. The corresponding CLI pairs are
`--cache-modes disabled,memory` and `--cache-modes disabled,redis`.
When `--cache-modes` is omitted, comparison defaults to disabled plus the actual
`configuration.cache_backend`; an approved configured Redis backend is therefore
used without a hard-coded memory fallback. Explicit requests to switch/create a
different backend fail before the first cache toggle. The matrix's optional
`--cache-backend` is likewise an assertion, not a provisioning choice.

An ordinary local smoke run without `POC_INTERNAL_API_TOKEN` can proceed with protected
metadata explicitly unavailable/null. Such a run does not prove application,
schema or dataset versions were captured. Supply approved internal access/token
for that evidence rather than filling in expected versions.
The shared client does not probe an anonymous metadata endpoint when no token
exists: it returns unavailable metadata without making a metadata HTTP request.
Authenticated reads use only `/internal/metadata`; there is no legacy `/metadata`
fallback. Fairness refresh uses the same canonical authenticated client path.

The application's metadata POC marker comes from application configuration,
not Azure resource validation. `poc_marker`, `environment`, `poc_mode`, and
`marker_source` must not be used alone as proof of disposable resource ownership,
synthetic database contents or authorization for destructive resets. Verify the
actual target and reset-specific database safeguards independently. The metadata
does not disclose real resource identifiers or endpoints.
The canonical controlled guard requires verified `poc_mode=true`,
`poc_marker=sql-vcore`, `environment=poc`, and the application's required
application/synthetic-data flags. A legacy response containing only `{poc:true}`
does not satisfy that guard. These checks complement, rather than replace,
verified SQL metadata, network/token controls and explicit operation approvals.

```powershell
.\.venv\Scripts\python.exe -m src.experiments.runner --profile connection-storm --host <base-url> --allow-host <base-url> --allow-unsafe-test --confirm-poc --connection-mode pooled
.\.venv\Scripts\python.exe -m src.experiments.runner --profile connection-storm --host <base-url> --allow-host <base-url> --allow-unsafe-test --confirm-poc --connection-mode no-reuse
.\.venv\Scripts\python.exe -m src.experiments.runner --profile slow-query --host <base-url> --allow-host <base-url> --allow-unsafe-test --confirm-poc
.\.venv\Scripts\python.exe -m src.experiments.runner --profile cache-comparison --host <base-url> --product-count <observed-product-count> --allow-host <base-url> --allow-unsafe-test --confirm-poc
```

These commands are bounded test examples, not authorization. The memory cache
comparison must run only in the permitted local/development environment; do not
relabel a cloud production app as development to bypass cache restrictions.
The cache comparison CLI uses `disabled` for its uncached mode; `redis` is optional
only after the external service, identity, consistency and cost prerequisites
are approved. Without a specific `--connection-mode`, the connection-storm
scenario compares bounded pooled and no-reuse modes; separate overrides above
make the tested mode explicit.

## Dataset and tuning

Select deterministic `small`, `medium`, or `large` data generation with seed 42;
`--rows` permits a deliberate override. Record actual row counts, database bytes,
seed, generator version, hot/cold skew, time anchor, and distribution. Validate
foreign keys, constraints, pagination stability, and transaction boundaries.
Reject a dataset that exceeds the configured storage cap.

### Dataset-state equivalence

Mixed-write workloads change inventory and work items. Reusing the same database,
seed, schema or workload hash does **not** establish the same starting dataset.
For provisioned 2/4 and serverless comparisons, either:

1. Use a genuinely read-only workload against a verified equivalent starting
   state, with no competing writers; or
2. Explicitly approve deterministic restoration/reset of the synthetic dataset
   **before each compared run**. A reset must verify the synthetic POC marker and
   retain `--allow-destructive-tests --confirm-poc`; never reset by default or
   interpret ordinary seed generation as an approved destructive reset.
   An application-configured POC marker alone is not database-content validation.

Record before/after dataset fingerprints, row and write-counter deltas, reset
provenance, dataset generator/version/seed, and each original run manifest.
Use a fresh idempotency namespace per run: replaying keys from an earlier run
can avoid actual writes and does not measure equivalent new-write cost.
If these conditions cannot be met, mark the runs **non-equivalent** and refuse
a fair-comparison claim. A reset does not itself equalize cache state or plans;
keep warm-up and tuning controls explicit.

The core's guarded reset entry point is:

```powershell
.\.venv\Scripts\python.exe -m src.database.manage seed --reset --allow-destructive-tests --confirm-poc --size small --seed 42
```

An optional `--rows <approved-row-count>` changes the deterministic dataset and
must match across comparisons. This is destructive to the synthetic POC data:
review the exact target and explicitly authorize each reset. It requires the
synthetic marker and ledger and uses an atomic transaction. Use the approved
administrative/reset identity, not the API runtime identity; do not replace the
guarded command with handwritten deletion SQL.
The previous mutated synthetic data is discarded, not saved and restored after
the test. Approve this data loss explicitly. Later restoration of compute,
tuning, cache or admission settings does not undo the reset.

`POC_MODE=true` is also required, and both confirmation flags are checked before
credential access. Inside the transaction, reset requires
`RuntimeConfiguration.dataset_kind='synthetic-v1'`, exactly one matching
deterministic seed ledger and no non-synthetic products. An older untagged
database is refused; do not silently retag it to bypass the guard. Delete/reseed/
deterministic insert are atomic and preserve tuning/migration state. Ordinary
`seed` remains non-destructive and can be a no-op for a matching ledger—it is
not reset after a mixed-write workload has mutated the data.

The reset JSON records `status=reset_and_seeded`, `destructive_reset`,
`previous_dataset_version`, `dataset_version`, `generation_seed`, `size`,
`products`, `work_items`, `dataset_state`, `dataset_state_fingerprint`, and
`dataset_fingerprint_scope=aggregate_state_not_full_content`.
This fingerprint summarizes counts/totals/IDs/activity/idempotency state, not
every row's content. It is **not cryptographic proof of identical row contents**.
An approved deterministic reset manifest plus matching aggregate baselines
supports the fairness claim with this limitation disclosed. Metadata refresh
exposes live `dataset_state`; the seed-ledger top-level `work_item_count` reflects
the original seeded count and must not replace current live state.
Accept only a successful reset manifest with `status=reset_and_seeded` for the
approved reset step; `already_seeded` is not equivalent. A failed reset command
or missing/invalid manifest must block the claimed controlled comparison.

Stop every API writer and drain/suspend the app's pool before resetting. Restore
the approved cache state separately; SQL reset alone does not invalidate a
distributed cache. Preserve each reset's JSON manifest. The matrix restores
admission in a `finally` cleanup path, including after a failure; that cleanup
verifies the same application instance and does not permit continuing a failed
case. Only a successful reset/validation
may proceed to refreshed metadata and the new metrics baseline in the prescribed
warm-up order.
Metadata refresh performs an additional SQL query for aggregate state: stop
writers, resume maintenance first, and refresh before the workload baseline,
never while collecting no-session idle evidence.
Matrix write-mix comparisons require
explicit reset-command opt-in **before every run, including the first**. Without
that approval and the required evidence, refuse a fair-comparison claim.
The [matrix reset option](test-matrix.md#optional-guarded-dataset-reset) is
disabled by default and additionally requires `--reset-dataset`,
`--confirm-no-other-sql-clients` and `--confirm-single-instance`, alongside the
existing destructive/POC/unsafe/execution gates. It derives the original seed
parameters from the verified ledger and resets before every selected case.

Standalone runner `--observe-dataset-state` opts into SQL-backed pre/post
metadata refresh; the matrix enables it automatically. It is observation, not
reset or proof of equivalent row contents, and never runs during an idle
observation interval or inside the measured workload UTC window. Preserve the
distinct observation timestamps and create-only initial/final run manifests;
mutable progress enrichment must not rewrite them. Default matrix comparisons remain
`non-equivalent-or-unverified`, regardless of matching profile or aggregate hashes.
The metadata SELECTs can warm SQL buffer/plan caches despite occurring outside
the measured interval. Disclose that effect and keep observation/warm-up order
consistent; an excluded query is not a claim that SQL cache state was untouched.

```powershell
.\.venv\Scripts\python.exe -m src.database.manage seed --size medium --seed 42
.\.venv\Scripts\python.exe -m src.database.manage tune --mode baseline --allow-unsafe-test
.\.venv\Scripts\python.exe -m src.database.manage tune --mode index --allow-unsafe-test
.\.venv\Scripts\python.exe -m src.database.manage tune --mode query --allow-unsafe-test
.\.venv\Scripts\python.exe -m src.database.manage tune --mode both --allow-unsafe-test
```

Run these tuning states as **separate experiments**, not consecutively without
measurements. Restore baseline before each isolated index/query test; confirm
actual objects/plans after changes. Compare execution count, total/average
duration, CPU, logical reads, plan, API percentiles, pool waits, and throughput.
Changing index and compute simultaneously does not isolate a cause.

The controlled slow-query comparison can automate the tuning/capacity sequence:

```powershell
.\.venv\Scripts\python.exe -m src.experiments.runner --profile slow-query --host <base-url> --compare-tuning --config <local-config-path> --original-tuning baseline --allow-host <base-url> --allow-unsafe-test --confirm-poc
```

It compares baseline/index/query/both at provisioned 2/4 using the same workload
hash and attempts restoration in a `finally` path. Fresh observed `tuning_mode`
is the default original mode; `--original-tuning` is optional when observed and
mandatory when observation is null. It is an assertion, not proof of actual
starting objects/plans, and a mismatch aborts before any mutation.
Before reading or changing compute, the comparison explicitly refreshes SQL
metadata and verifies the same original process instance. Authenticated
`GET /internal/metadata?refresh_database=true` returns top-level `tuning_mode`
from `dbo.RuntimeConfiguration`. Capture it before the metrics baseline and
compare any explicit assertion with the observed value. If it is null/unknown,
require an explicit reviewed `--original-tuning` or abort the restoration-sensitive
scenario; never assume baseline. A reported mode still warrants verification of
actual objects/plans. The example's `baseline` assertion is valid only when it
matches the observed state or is the approved assertion for a null observation.

Persist original compute configuration. This comparison accepts only restorable
GP Gen5 original 2/4-vCore SKUs; unsupported families and unknown serverless
minimum/pause settings fail preflight, never default to 2. Restore exact original
capacity/tier/minimum/pause and verify full SKU, maximum size, zone redundancy,
read scale, license type and backup redundancy. This is the current automation's
restoration envelope, not the full Azure product capability range.
Verify observed restoration independently. All controlled
token, dataset-equivalence and operational approvals still apply; a failed
restoration must be reported rather than hidden by successful workload results.

## Cache comparison

Cache is off by default. **The local in-memory cache is not a production
distributed-cache design.** It is process-local, loses entries on restart, and
does not coordinate invalidation across workers/replicas. Keep the one-process
test topology fixed and disclose that limitation.

Cache only explicitly suitable read endpoints. Do not cache transactional,
authorization-dependent, or read-after-write-sensitive responses without an
approved consistency design. Compare identical cold and warm phases; record TTL,
eviction, hit/miss counts, SQL calls avoided, memory, dependency latency, stale
reads after writes, and API latency. A hit-ratio increase alone is not proof of
correctness or lower total cost.

Optional Azure Cache for Redis support is a compatibility path, not a default paid
resource. For new deployments prefer **Azure Managed Redis** subject to explicit
approval and compatibility validation. The explicit
`enable_legacy_redis=false` option keeps the Standard C1 Redis 6 module off.
When separately approved, it uses private connectivity and runtime Entra
Data Contributor access, not access keys. This tier/version is a
**POC assumption, not a confirmed customer requirement.**

Microsoft's July 2026 update removed the
planned October 2026 creation block for **existing** Basic/Standard/Premium
customers; the new-customer block started April 1, 2026 and retirement remains
September 30, 2028. Do not use the older contradictory timeline lower on the same
page. Verify current cloud-specific eligibility before provisioning:
[official updates](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-whats-new).

## Matrix and experiment hygiene

See [the 15-test matrix](test-matrix.md). The matrix runner must not be interpreted
as authorization to scale, change tier, fail over, or create paid resources.
Separate configuration-changing operations and explicit approval from workloads.
Keep raw artifacts under ignored `results\local-untracked-runs`; see
[evidence](evidence-guide.md) and [result template](results-template.md).

Record warm-up policy, repetitions, random seed, cache state, UTC synchronization,
runner host limits, and background activities. Use at least repeated comparable
runs when feasible, report variability, and do not average p95/p99 values to form
a combined percentile. Analyze raw samples or a compatible histogram instead.
