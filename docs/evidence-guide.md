# Evidence collection and sanitization

Evidence is a product of an executed test, not generated prose. Current cloud
results: **Not demonstrated by this POC run.** Unknown customer objectives remain
**TBD**; default experimental values are a **POC assumption, not a confirmed
customer requirement.**

## Run lifecycle

1. Allocate a unique nonpersonal run ID; record versions, config, hashes, dataset,
   source workload horizon, acceleration, target/achieved rate and UTC window.
2. Record preconditions and the one intended changed variable. Keep requested
   and observed configuration separate, including restored configuration.
3. Run workload and capture raw request/outcome/attempt data where available.
   Refresh database metadata before the application baseline, then collect
   baseline/end cumulative snapshots from the same `instance_id`. Preserve
   snapshots, timestamps and restart/confounding-traffic checks alongside deltas.
   Preserve verified adapter, schema/dataset/tuning metadata and
   `dataset_size={product_count,work_item_count,counts_source}`. Keep the strict
   refresh → baseline counters → workload → end counters → refresh order.
   For product-ID workloads, explicit product-count overrides must fit observed SQL data and remain
   identical across comparisons; memory/unverified SQL runs are not SQL proof.
   Require both `repository_backend=sql` and `sql_adapter_configured=true`.
   Department-only diagnostics are exempt only from the product-ID bound.
4. Collect platform metrics for the **same** database and exact UTC window;
   collect Query Store/DMV information after idle/resume tests, never during the
   intended no-session interval.
5. Collect control-plane activity/state for scale/pause/resume/failover and
   separately observed client recovery.
6. Record current retail input metadata and usage units; do not synthesize a
   cost value when an input is missing.
7. Generate factual observations and a report using [templates](results-template.md).
8. In a cloud runner, upload the complete raw file inventory to private Blob
   Storage and require successful persistence. Download through approved private
   connectivity, verifying the run prefix, file list and SHA-256 hashes.
9. Sanitize into a separate destination, scan and manually review before sharing.

## Artifact contract

Real runs belong under ignored `results\local-untracked-runs\<test-run-id>`.
The following is the complete bundle contract, not a claim all files contain
measured data after any one command:

| Artifact | Required contents |
| --- | --- |
| `manifest.json` | Mutable progress/enrichment view: run ID, exact UTC, versions/hashes, changed variable, acceleration, coverage and control metadata |
| `manifest.initial.json` | Create-only initial run snapshot, baseline dataset state/fingerprint scope, control state and unique run/idempotency namespace |
| `manifest.final.json` | Create-only final snapshot, before/after dataset observations, process-counter deltas and reset provenance where applicable |
| Matrix-root `reset-provenance-test-NN.json` when reset is enabled | Per-selected-case administrative reset receipt, verified original synthetic seed parameters, reset outcome and post-reset validation |
| `configuration.json` | Requested/observed service/compute/hardware/vCore/storage/zone/backup/pause/app settings |
| `workload-summary.json` | Attempted/completed/read/write counts, rate and latency definitions, duration and profile overrides |
| `application-metrics.json` | Request/dependency/pool/concurrency/cache counters, percentiles, coverage and sampling |
| `azure-sql-metrics.json` | Metric names/units/aggregation/grain/time series/coverage, serverless billed Total where available |
| `collection-coverage.json` for REST cloud collection | Required/optional source coverage, measured/incomplete status and bounded safe error categories; never inferred zeroes |
| `query-store-summary.json` | Safe aggregated query/plan statistics, capture settings/window/coverage, no raw SQL text |
| `sql-diagnostics.json` when SQL collection is requested/skipped | Private schema/ledger, aggregate dataset state, resource/storage diagnostics and explicit coverage/skip reasons |
| `error-summary.json` | Defined final-outcome categories/counts and sanitized codes |
| `retry-summary.json` | Attempts and logical-operation rates, decisions/delays/budget and final results |
| `cost-inputs.json` | Dated region/currency/SKU/meter/unit and quantity inputs, estimates explicitly separate |
| `observations.md` | What happened, anomalies, causal uncertainty, missing evidence and next test |
| `executive-summary.md` | Decision-relevant findings with source links and limitations |
| `sanitization-report.json` | Sanitizer version/scope/replacement classes, rejected files and manual-review status |

For a missing source, preserve a structured missing/coverage status and the exact
statement **Not demonstrated by this POC run.** Do not populate numeric zero or a
plausible sample as if observed. Sanitized examples are explicitly empty/template
examples, not benchmark results.

Preserve initial/final snapshots exactly as written. The runner never rewrites
these create-only files; subsequent collector enrichment belongs in the mutable
view with its own observed timestamp/source. Do not retrospectively insert
measurements into an initial snapshot. Application create-only behavior is not
an Azure WORM policy or protection from a privileged filesystem editor.
Include snapshots and reset receipts in the private full-file archive. Do not
assume new raw files or fields are automatically approved for public export;
the sanitizer's allowlist and human review still apply.
Matrix results bind the final snapshot SHA-256; verify the referenced digest.
Reset provenance records the original ledger-derived seed parameters and
generator hash, and explicitly records that previous mutated data is not
restored. Manifests are provenance, not backups of every discarded row.

Standalone `--observe-dataset-state` enables protected SQL-backed pre/post
metadata refresh; matrix execution enables it automatically. Refresh only
outside no-session idle periods and the measured workload UTC window. Keep
observation timestamps distinct from measured start/end. Equal hashes do not
change the matrix's default
`non-equivalent-or-unverified` comparison status. Preserve the reset and
quiescence evidence needed for an independent comparison assessment.

## Local and cloud persistence

The Container Apps runner uploads **all files** in its raw run directory,
including the required manifest/report artifacts, under a unique run-ID prefix
in a private Azure Blob container. The container's account has private endpoint
and DNS connectivity. No account key, SAS token, public container or storage
connection string is required.

| Setting/control | Contract |
| --- | --- |
| `EVIDENCE_STORAGE_ACCOUNT` | Private runtime environment setting identifying the evidence account |
| `EVIDENCE_STORAGE_CONTAINER` | Private runtime environment setting identifying the container |
| `AZURE_CLIENT_ID` | Selects the runner's managed identity in Azure; never publish an actual value |
| SDK authentication | Cloud `DefaultAzureCredential(managed_identity_client_id=AZURE_CLIENT_ID)` is constrained to managed identity; local operators explicitly use `AzureCliCredential`; BlobServiceClient uses the HTTPS blob endpoint |
| Runner authorization | Scoped Storage Blob Data Contributor; role assignment does not replace private network/DNS access |
| Prefix | Content-addressed `runs/<safe-run-id-or-bundle-hash>/<content-hash-prefix>`; no customer name or environment identifier |
| Upload success | Every raw file and required output persisted; completion manifest records complete filenames/lengths/SHA-256 and the upload receipt binds its full hash |
| Upload failure | Nonzero runner/job result with exact status `private-evidence-persistence-failed`; never successful completion with only console output |
| Cloud job without a destination | Fails closed rather than silently falling back to ephemeral files |
| Local run without storage settings | Files persist in the ignored local output directory normally |

When either the storage environment or the local configuration's
`evidence_storage_account`/`evidence_storage_container` settings are present,
persistence is mandatory rather than a
best-effort optional step. Treat partial uploads as incomplete; preserve private
diagnostics and verify the full inventory before relying on the run. A failed
workload can still have useful persisted failure evidence; distinguish workload
outcome from persistence outcome. Do not overwrite another run's artifacts.
Upload happens after evidence finalization and comparison restoration, including
matrix/cache/storm/tuning comparison roots. A container with public blob access
enabled is rejected; this check does not replace verifying the account's private
network settings.

The storage module writes `archive-manifest.json` **last** as the completion
marker. It contains every raw filename, length and SHA-256 digest. An incomplete
prefix without a valid complete manifest is not a successful archive. Retry
behavior must preserve matching existing content and reject mismatches; these
overwrite/idempotency controls are not an Azure immutable-retention policy.

To retry persistence of an existing approved raw bundle without rerunning the
workload:

```powershell
.\.venv\Scripts\python.exe -m src.experiments.storage --run-dir <private-run-directory> --config <local-config-path>
```

The optional `--credential azure-cli` or `--credential managed-identity` selects
the appropriate approved execution context. Runtime environment configuration
uses `AZURE_CLIENT_ID` as the **client ID**, not the identity's object/principal
ID. Keep configuration-only retry/download operators on an approved private
network and grant only the necessary data permissions.

`POC_EVIDENCE` is now **receipt-only**: artifact file/hash/byte information and
prefix, with neither raw nor sanitized artifact payloads. The complete archive
inventory is also in `archive-manifest.json` and local
`cloud-archive-receipt.json`. `POC_EVIDENCE_UPLOAD` records completion with the
safe prefix, full manifest SHA-256 and count. Verify that full manifest hash,
then the complete file inventory; prefix/count alone is insufficient. Receipt
logs do not replace the full private artifact set.
Raw metrics/configuration/request files can contain environment metadata and
must not be printed or published simply because the data model is synthetic.
An ordinary smoke run without approved internal-token access can lack protected
metadata. Preserve unavailable/null values and the missing-evidence status; a
successful HTTP request or durable upload does not prove versions, seed counts,
tuning or process counters were observed.

### Download and verification

Use `src.experiments.storage` from an **authorized VNet-connected host**. Select
the run ID and full manifest SHA-256 from the receipt, and a new ignored
destination:

```powershell
.\.venv\Scripts\python.exe -m src.experiments.storage --run-id <run-id-from-receipt> --output <new-ignored-download-directory> --manifest-sha256 <full-manifest-sha256> --config <local-config-path> --credential azure-cli
```

Select an approved Azure CLI identity and separately grant Storage Blob Data
Reader at the approved scope. The operator does not inherit the runner's
blob-write role. The destination must not exist; corrupt/incomplete downloads
remove the new destination rather than leave a success-shaped partial bundle.
Alternatively, use `--download-prefix <exact-upload-prefix>` instead of
`--run-id`; the selectors are mutually exclusive. `--output` aliases `--run-dir`.
Upload/retry mode uses `--run-dir` and omits run-ID/download-prefix/manifest-hash
download selectors.
Take the run or bundle identifier from the `POC_EVIDENCE_UPLOAD` prefix rather
than guessing it from a nested workload. Matrix snapshots can use a
`bundle-<bundle-hash>` identifier. The full `--manifest-sha256` is required for
receipt-bound verification. Storage has no shell wrapper; invoke the module
directly. After downloading a matrix archive, sanitize individual complete run
directories rather than its parent snapshot.

1. Resolve the private blob endpoint and confirm network reachability.
2. Confirm the intended identity and storage scope privately; do not print them.
3. Download only the selected run prefix into a new ignored directory.
4. Verify the completion manifest against the receipt's full hash, then every
   listed path, length and SHA-256; reject missing/mismatched files or unsafe
   output paths.
5. Confirm all required artifact names and missing-data statuses.
6. Run the existing sanitizer/scanner and human review on a separate destination.

An operator outside the private network cannot download directly despite having
RBAC permissions. Use approved private connectivity, not a public-access
exception, shared key or SAS workaround.

A VNet-connected local runner remains an alternative source of full artifacts.
Platform/Query Store collection can require a separate diagnostic identity and
permission scope. Persisting the required files does not prove that every source
was available: absent measurements retain the required missing-evidence status.

### Separate workload, monitoring and SQL permissions

The runner's Blob Data Contributor role authorizes evidence storage only. It does
not grant SQL access, Azure Monitor reads or Log Analytics queries. Separately
approve the minimum necessary resource-read/monitoring actions at the SQL
resource scope and query permissions at the intended workspace scope. Confirm
effective access with a bounded collection probe, not by assuming a role's name
proves all required operations.

### CLI-free cloud monitoring collector

The implemented `src.experiments.cloud_evidence` REST collector uses `httpx` and managed-identity-only
`DefaultAzureCredential`; Azure CLI is not required **inside the job** for
database configuration, platform metrics or correlated workspace-log collection.
Environment/client-secret, CLI and browser credential fallbacks are excluded.
Verify the selected user-assigned identity and effective resource-scoped roles.

| Private runner setting | Purpose |
| --- | --- |
| `SQL_RESOURCE_ID` | SQL **database ARM resource ID**, not logical-server scope |
| `AZURE_SUBSCRIPTION_ID` | Scope approved management-plane requests |
| `LOG_ANALYTICS_WORKSPACE_ID` | Workspace **customer GUID**, not the workspace ARM resource ID |
| `AZURE_CLIENT_ID` | Runner user-assigned identity **client GUID**, not its principal/object ID |
| `EVIDENCE_COLLECTION_WAIT_SECONDS` | Optional ingestion wait, 0–240 seconds; default 120 seconds |

The ingestion wait, 300-second request-scheduling deadline, maximum 48-hour UTC
window, 8-MiB response cap and at most three retries are a
**POC assumption, not a confirmed customer requirement.** Redirects are disabled.
The scheduling deadline is not a guarantee that the whole process finishes
within 300 seconds; these bounds are not ingestion SLAs. Record delayed/absent
samples rather than silently extending the measured workload window.

The cloud-job launcher automatically requests `--collect-cloud` and
`--observe-dataset-state`; the runner also requires cloud collection in its
job environment. For standalone collection from the approved managed-identity
environment, use the same settings without a configuration file:

```powershell
.\.venv\Scripts\python.exe -m src.experiments.evidence --run-dir <private-run-directory> --cloud-rest
```

This is not a local Azure CLI credential fallback. It requires a working
approved managed-identity endpoint. The REST collector opens **no SQL connection**
and does not query Query Store or elevate database privileges. The launcher's
separate `--observe-dataset-state` feature calls protected API metadata, which
does perform SQL pre/post refresh outside the measured workload window; do not
mistake that observation for permission to query during idle.
Those metadata SELECTs can warm SQL buffer/plan caches even though excluded from
the measured interval. Record this limitation and use consistent observation
and warm-up order. Do not call the resulting baseline an untouched cold database.

| REST source | Implemented endpoint/version and audience |
| --- | --- |
| Database configuration | ARM SQL database API `2023-08-01` |
| Metric definitions | ARM metricDefinitions API `2018-01-01` |
| Metric time series | ARM metrics API `2023-10-01` |
| ARM authentication | `https://management.azure.com/.default` |
| Workspace queries | `https://api.loganalytics.azure.com`; separate token scope `https://api.loganalytics.io/.default` |

Never reuse the ARM token for the Log Analytics audience. The newer query host
does not by itself change the documented token audience. See official
[Log Analytics access/authentication](https://learn.microsoft.com/azure/azure-monitor/logs/api/access-api),
[response format](https://learn.microsoft.com/azure/azure-monitor/logs/api/response-format)
and [Metrics - List](https://learn.microsoft.com/rest/api/monitor/metrics/list?view=rest-monitor-2023-10-01).
Reachability to these authenticated service endpoints is distinct from private
SQL/API/Blob connectivity.

Required collection includes database configuration, CPU/data-I/O/log-I/O/
workers/sessions observations, correlated logs, and billed vCore-seconds for
serverless. Missing required sources produce **incomplete collection and a
nonzero result**, not a successful all-null evidence bundle. Optional gaps are
explicitly classified `measured-with-gaps`. Both `measured` and
`measured-with-gaps` describe only this **Azure Monitor subset**, not complete
POC evidence or SQL-observer coverage. Workspace correlation uses verified table
schemas; no correlated log observations is incomplete. Inspect
`collection-coverage.json` and the manifest rather than merely
checking that files exist. A metric sample's presence does not establish full
window coverage or causality.

Query Store, direct SQL diagnostics and pricing remain explicitly unmeasured
through this REST path and require a separate approved observer/operator
collection step. Missing values remain **Not demonstrated by this POC run.**
Error ledgers retain HTTP status codes and categories, not tokens, full request
URLs or response bodies. Failure artifacts and coverage are still archived in
the runner's `finally` persistence path; a successfully archived failure remains
a failed/incomplete collection.
Local contract tests do not establish live endpoint access, identity grants,
sample coverage or successful deployment. Rebuild the approved image and apply
the environment/role wiring before live validation; local source changes alone
do not update an existing job's image. Live REST collection:
**Not demonstrated by this POC run.**

### Current runtime-image limitation

The baseline Python image does **not** install Azure CLI. HTTP workloads, the
managed-identity REST cloud collector and SDK Blob persistence do not need it.
External job submission still uses an authorized workstation Azure CLI.
Operator `--config` collection, management-plane idle controls and matrix
operations still require the CLI-equipped authorized environment, with private
connectivity where API/SQL access is needed. The new REST collector does not
implement all management operations or make baseline-image idle/matrix paths
available. SQL assets in the image do not establish observer permission.

The narrow monitoring assignments are Reader on the SQL database and Log Analytics
Reader on the selected workspace, in addition to evidence-container Blob rights.
Verify actual effective grants. API errors, denied access, unavailable metric
definitions and absent samples must remain explicit coverage failures—not a
success-shaped bundle of unmeasured default numbers. Operator-side read-only
retail-price collection does not require direct private SQL connectivity.

SQLAlchemy/ODBC Query Store and DMV collection uses the selected identity's
**database permissions**, independently of Azure RBAC. Use a reviewed contained
observer principal or approved diagnostic context with only the permissions
required by the actual diagnostic queries. Do not reuse the bootstrap
administrator or grant the runner schema/write/admin rights merely to fill an
evidence field. If SQL diagnostic access is absent, report the exact missing
source; never substitute platform CPU percentage for Query Store or billed
vCore-seconds.

Database diagnostic queries can keep serverless active. Run them outside the
C2 no-session interval; use management-plane state and metrics during idle.
Record denied/unsupported/late sources explicitly even when all resulting files
were durably uploaded.

### Bounded SQL diagnostics

The separate **operator/configuration-based** collector attempts read-only SQL
diagnostics by default when `--config` is supplied; a local/operator runner's
`--collect-cloud` with configuration can also invoke it. This is not the cloud-job
REST path, which never opens a diagnostic SQL connection.
It checks the management-plane database state first. Non-Online or unavailable
state skips SQL without a connection probe. With Online state and approved
access, it uses the core Azure Identity/ODBC 18 SQLAlchemy engine with `NullPool`,
bounded login/command timeouts, and disposal after reads. The current 5-second
login and 10-second command bounds are a **POC assumption, not a confirmed
customer requirement.**

Collected sources include schema/catalog and migration ledger, live aggregate
dataset state, UTC-filtered `sys.dm_db_resource_stats`, storage-file information,
Query Store configuration and parameterized run-window query/wait summaries.
The Query Store queries reuse `sql\query-store\top-queries.sql` and `waits.sql`;
counts and weighted CPU/duration/read statistics retain their declared units.
An accessible migration ledger can update manifest `schema_version` with its
observation timestamp/source. Dataset aggregates require quiescence and remain
aggregate-only fingerprints, not proof of identical row content.

No raw SQL text or raw error strings are exported. Missing network, database
permission or schema support produces explicit unavailable/null sections with
**Not demonstrated by this POC run.** `sql-diagnostics.json` stays private;
sanitized Query Store summaries retain only approved numerical statistics and
pseudonymized query/plan references.

**Online is not permission to disturb an idle trial.** A query while the
database is Online but waiting to auto-pause can reset its idle timer; state can
also change after the check. During any intended no-session interval, use the
collector's explicit `--skip-sql`, or postpone collection. Do not add a guessed
runner flag; invoke platform-only collection through the documented entry point:

```powershell
.\.venv\Scripts\python.exe -m src.experiments.evidence --run-dir <private-run-directory> --config <local-config-path> --skip-sql
```

This records SQL diagnostics as skipped/unavailable, not validated. Query Store
overlap, capture lag, retention and other traffic mean a UTC-bounded query is not
necessarily run-exclusive. Read-only capability tests are not evidence that
live diagnostic permissions, data or timing were demonstrated.

## Command entry points

Prefer direct Python modules and inspect their current arguments first.
Optional wrappers forward arguments where shell policy permits; AST-only checks
do not demonstrate wrapper execution:

```powershell
.\.venv\Scripts\python.exe -m src.experiments.cloud_job --help
.\.venv\Scripts\python.exe -m src.experiments.matrix --help
.\.venv\Scripts\python.exe -m src.experiments.evidence --run-dir <private-run-directory> --config <local-config-path>
.\.venv\Scripts\python.exe -m src.experiments.sanitize --run-dir <private-run-directory> --output <new-sanitized-directory> --redactions <local-redaction-list-path>
.\.venv\Scripts\python.exe -m src.experiments.scan --help
```

The implementation modules include `src.experiments.cloud_job`,
`src.experiments.matrix`, `src.experiments.evidence`, `src.experiments.storage`,
`src.experiments.sanitize`, and `src.experiments.scan`. The
[cloud launcher](workload-guide.md#private-cloud-execution-contract) records
the exact execution and upload receipts; it does not replace the separate
private Blob download and cryptographic verification step.
CLI paths/configuration and all outputs stay local and
untracked. Run collection after cloud ingestion has caught up; distinguish late
data from no events. Do not repeatedly collect SQL during C2 waiting.

The collector can accept `--attempts <private-attempt-file>` and
`--query-store <private-query-store-file>` when those sources have been collected.
`--attempts` requires **JSONL**, matching `event="operation_attempt"` and the exact
`test_run_id`, with only supported attempt fields retained. It does not accept a
single JSON array or infer attempts from arbitrary request logs or HTTP errors.
`--query-store` accepts an operator-exported JSON summary. The collector records
it as operator-provided, with window alignment requiring review against the
manifest UTC interval; it does not independently verify that alignment or
prove run exclusivity. Supplying this file bypasses live Query Store queries,
but other SQL diagnostics still run unless `--skip-sql` is also supplied.
Keep raw SQL text private and inspect the source interval before comparison.
Use `--verified-table <table-name>` only after inspecting that actual workspace
schema; the option is repeatable for supported tables. The sanitizer's local
redaction file is a JSON list of private terms.
For a reviewed synthetic-only run, `--confirm-no-customer-data` is the explicit
alternative to a redaction list, not a bypass of scanning/manual review. The
output must be a new directory distinct from raw input; existing destinations
and archives must not be overwritten.

Sanitize **one complete run directory** at a time, not a matrix's parent folder.
After schema allowlisting and a successful scan, the sanitizer writes a new
shareable directory and an adjacent ZIP; failures remove the incomplete output.
Review and scan both forms. Raw Locust/request logs, SQL and error Markdown are
not copied as publishable evidence; safe numerical Markdown is regenerated and
run/correlation identifiers use stable pseudonyms. Retain the original private
source and document any excluded evidence rather than treating the reduced
bundle as complete raw telemetry.

## Sanitization rules

Use structured allowlisting plus replacement of subscription/tenant/principal
identifiers; resource-group/server/database names; endpoint/host names; IP
addresses; usernames; customer terms; tokens; connection strings; raw SQL and
parameters; and local paths containing personal information.

Provide customer-specific terms privately to the sanitizer/scanner where
supported. Pattern recognition alone cannot know every customer identifier.
Review filenames, nested keys, CSV headers, metadata and archive contents as well
as values. Exclude images/binaries by default unless independently reviewed.
Never copy raw material into a public staging directory as an intermediate step.

Do not redact units, configuration categories, error **categories**, metric
definitions or timing in ways that misrepresent the result. If precise timestamps
or configuration details cannot be shared, state the transformation and its
analytical limitation. Public role names are descriptive placeholders, not
principal identities.

After sanitization:

1. Scan destination worktree, staged content, history and all shareable files.
2. Manually inspect the bundle's manifest, every text file and any archive.
3. Verify source/result provenance and that absent measurements remain absent.
4. Confirm separate sections for measured results, cost estimates, documentation,
   guidance, recommendation and remaining unknowns.
5. Approve the exact bundle and publish only that sanitized copy.

## Interpreting coverage

Record metric intervals received versus expected, sampling and percentile scope,
clock alignment, warm-up exclusions, failure exclusions, logging loss, runner
limits, unknown classifications and actual achieved demand. Query Store intervals
may straddle run boundaries; report overlap rather than silently attributing the
whole interval. Aggregate request percentiles from raw compatible samples, never
by averaging per-minute percentiles.

High CPU correlated with latency supports investigation, not a standalone causal
conclusion. Local fault-injection tests validate policy paths, not Azure scaling,
pause, availability or DR. See [metrics](metrics-catalog.md),
[publication checklist](public-repo-checklist.md), and [results](results-template.md).

Storage references:
[Entra authorization for Blob Storage](https://learn.microsoft.com/azure/storage/blobs/authorize-access-azure-active-directory),
[private endpoints](https://learn.microsoft.com/azure/storage/common/storage-private-endpoints),
[Python Blob SDK](https://learn.microsoft.com/python/api/overview/azure/storage-blob-readme).

Monitoring authentication reference:
[Log Analytics API access](https://learn.microsoft.com/azure/azure-monitor/logs/api/access-api).
