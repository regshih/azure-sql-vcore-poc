# Azure SQL Database vCore evaluation POC

A synthetic, reproducible evaluation of **Azure SQL Database** General Purpose
provisioned and serverless compute. This is not Managed Instance, SQL Server on a
VM, a production sizing recommendation, or a published benchmark.

Every default is a **POC assumption, not a confirmed customer requirement.**
Unmeasured outcomes must be reported as **Not demonstrated by this POC run.**
Do not put customer data, credentials, environment identifiers or raw evidence
in this repository.

## Start here

1. Complete the [customer workshop](docs/customer-workshop.md) and review
   [assumptions](docs/assumptions.md).
2. Read the [architecture](docs/architecture.md),
   [diagrams](docs/architecture-diagram.md) and [security guide](docs/security-guide.md).
3. Validate locally, then follow the [deployment guide](docs/deployment-guide.md).
4. Execute the [workload guide](docs/workload-guide.md) and compare equivalent
   runs using the [results template](docs/results-template.md).
5. Sanitize evidence using the [public-repository checklist](docs/public-repo-checklist.md).
6. Delete billable POC resources when finished. They do not expire automatically.

## Architecture and baseline

```text
Private workload runner / VNet-connected operator
                    |
             Internal Container Apps API
                    | managed identity + encrypted TDS
             SQL private endpoint
                    |
       Azure SQL Database GP, Gen5, 2 vCores

Bootstrap job: separate Entra SQL administrator identity -> migrate / seed / grants
Runner job: synthetic traffic -> private Blob evidence storage
API telemetry + platform diagnostics -> Application Insights / Log Analytics
ACR: immutable image digest, managed-identity image pulls
Optional: 4-vCore comparison, serverless, cache, cross-region failover group
```

| Setting | Starting point |
| --- | --- |
| Database | General Purpose, provisioned, Standard-series Gen5, 2 vCores |
| Storage cap | 5 GB, configurable; synthetic data must fit |
| App | Python 3.12+, FastAPI, SQLAlchemy, pyodbc / Microsoft ODBC Driver 18 |
| API hosting | Container Apps Consumption; 0.5 vCPU / 1 GiB; one replica |
| SQL identity | Microsoft Entra-only; no SQL administrator password |
| Runtime identity | Separate, least-privilege contained SQL user |
| Networking | SQL/Blob private endpoints and private DNS; internal app environment |
| Cache | Disabled; development memory cache is not a distributed-cache benchmark |
| DR / Business Critical | Optional, not enabled by the baseline |
| Region / budget / RTO / RPO / latency targets | Customer input; **TBD** |

**Why 2 vCores:** it is a small, explicit, fixed-compute reference point that
helps attribute performance to workload, queries, concurrency and resource
pressure. It is not sized from "10 users", "100 users", or 50,000 daily reads.
Scale only after measuring the bottleneck and checking query/index/app behavior.

**Why serverless:** variable demand and long idle periods can justify a different
compute/billing model. C1 disables auto-pause for steady/variable/spike comparisons;
C2 measures actual pause/resume separately. Suggested bounds are 0.5 minimum and
4 maximum, **only where subscription/region capabilities support them**. Memory
can raise billed compute above the minimum vCore setting. Serverless is not
unlimited scaling, burst credits, or necessarily cheaper.

See [provisioned versus serverless](docs/provisioned-vs-serverless.md),
[serverless decision guide](docs/serverless-decision-guide.md) and
[scaling decision guide](docs/scaling-decision-guide.md).

## Local setup

Run commands from the repository root. Python 3.12+ and Git are required.
The local memory backend uses synthetic, process-local data and is not SQL evidence.

PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:APP_ENVIRONMENT = "local"
$env:REPOSITORY_BACKEND = "memory"
$env:HOST = "127.0.0.1"
$env:PORT = "8000"
.\.venv\Scripts\python.exe -m src.api
```

Bash:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
APP_ENVIRONMENT=local REPOSITORY_BACKEND=memory HOST=127.0.0.1 PORT=8000 \
  .venv/bin/python -m src.api
```

Open `http://127.0.0.1:8000/docs`. The launcher binds loopback by default.
[.env.example](.env.example) documents configuration; it is not automatically
loaded. Never create or commit a populated `.env`.

Memory mode is forbidden in production/cloud hosting. There is no fallback from
unavailable SQL to synthetic memory data. Keep local mode on loopback; CORS is
not authentication. Use one process for memory-mode demonstrations.

### API surface

| Purpose | Request |
| --- | --- |
| Liveness, no SQL access | `GET /healthz` |
| SQL/repository readiness | `GET /readyz` |
| Product point read | `GET /api/products/{product_id}` |
| Filters / keyset pages | `GET /api/products?department=operations&q=SYN-&limit=25` |
| Bounded product batch | `POST /api/products/batch`, body `{"ids":[1,2,3]}` |
| Work-item point read | `GET /api/work-items/{work_item_id}` |
| Work-item filter / page | `GET /api/work-items?status=open&limit=25` |
| Bounded work-item batch | `POST /api/work-items/batch` |
| Transactional write | `POST /api/work-items`, `Idempotency-Key` required |
| Aggregate dashboard | `GET /api/dashboard` |
| Recent activity | `GET /api/activity?limit=25` |

Synthetic write body:

```json
{"title":"Synthetic evaluation request","lines":[{"product_id":1,"quantity":2}]}
```

Idempotency is durable with the SQL backend; an identical replay returns the
original result, not another stock change. A different payload with the same key
conflicts. Pages return `items` and `next_cursor`; reuse the cursor with the same
filters. The insertion watermark does not freeze updates or provide a historical
snapshot. Money uses integer cents.

## Validate before deployment

```powershell
.\.venv\Scripts\python.exe -m build
.\.venv\Scripts\python.exe -m pytest tests
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m ruff format --check src tests
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m src.operations.validate
```

The validator reports executed, failed and unavailable checks separately.
Unit/local integration tests do not demonstrate SQL Server transaction semantics,
real Azure resilience, saturation, billing, auto-pause or DR.
Live SQL and cloud tests require explicit configuration; see
[deployment guidance](docs/deployment-guide.md).

CI runs quality/security checks, **not automatic deployment**. The separate
manual cloud workflow requires an operator-configured protected GitHub environment,
reviewer approval and OIDC federation. Never add an Azure client secret.

## Deploy the private baseline

Install Azure CLI and sign in with `az login`. Install ODBC Driver 18 for any
machine executing SQL directly. Local Docker is not required: deployment uses
ACR remote build. The operator needs appropriate provisioning/RBAC permissions;
the bootstrap job and application do not inherit the operator identity.

```powershell
Copy-Item deployment.example.json deployment.local.json
# Edit deployment.local.json: subscription, dedicated rg-... name, unique prefix, region.
.\.venv\Scripts\python.exe -m src.operations.cli capabilities --config deployment.local.json
.\.venv\Scripts\python.exe -m src.operations.cli price-inputs --config deployment.local.json
.\.venv\Scripts\python.exe -m src.operations.cli deploy --config deployment.local.json --what-if-only
.\.venv\Scripts\python.exe -m src.operations.cli deploy --config deployment.local.json --confirm-poc
```

The local JSON is gitignored and receives deployment outputs. **Never force-add it.**
Deployment validates Bicep, checks capabilities, previews changes, deploys shared
resources, builds an image, pins its digest, deploys API/jobs, runs bootstrap and
then private smoke validation. No populated `.env`, registry password or SQL
password is created. Re-running deployment preserves data but may return SQL
configuration to the values in the local configuration.

Smoke verification requires successful SQL-backed business requests, cloud
evidence collection and job-side SHA-256 readback of the complete private Blob
archive. A successful job status or `/healthz` response alone is insufficient.
Independent operator download remains a separate verification step.

Deployment generates an internal-control bearer token in an ephemeral OS-temporary
ARM parameter file, deletes that file even on failure, and stores the token only
as encrypted Container Apps secrets shared by the API and runner. It is never
written to deployment configuration or retained diagnostic artifacts. Application
redeployment rotates both copies; do not redeploy during a measured run.

Optional local configuration flags are `enable_business_critical`,
`enable_legacy_redis`, `enable_sql_diagnostics`, `enable_alerts`, and `enable_dr`;
all default false.
Business Critical requires an explicit opt-in, provisioned compute and an actual
regional capability check; the standard comparison matrix remains General Purpose.
The Redis extension is private, Entra-authenticated legacy Azure Cache for Redis
compatibility. Creation restrictions and retirement apply; prefer Azure Managed
Redis for a new cache design. Neither extension is evidence of improved performance.
Alert activation additionally requires `alert_owner`, `alert_action_group_ids`
and `alert_runbook_base_url`. Review `alert_thresholds`, actual ingestion,
notification routing and noise behavior first; see the
[alert templates and runbooks](docs/alerting-guide.md).

The secure app is intentionally not reachable from the public internet. Execute
traffic from the runner job or a VNet-connected client. Do not "fix" connectivity
by enabling broad SQL firewall rules. The separate evaluation profile is an
explicit opt-in with one exact caller IPv4 address; it is not production guidance.

All normal mutations require `--confirm-poc`, and existing resources must carry
`poc=sql-vcore` and `environment=poc`. Destructive operations have additional flags.
These guards reduce mistakes; they are not an authorization system.

## Run expected, peak and spike experiments

From another terminal, with the local app or a reachable private app running:

```powershell
.\.venv\Scripts\python.exe -m src.experiments.runner --profile smoke --host http://127.0.0.1:8000
.\.venv\Scripts\python.exe -m src.experiments.runner --profile expected --host http://127.0.0.1:8000
.\.venv\Scripts\python.exe -m src.experiments.runner --profile peak --host http://127.0.0.1:8000
.\.venv\Scripts\python.exe -m src.experiments.runner --profile spike-1-minute --host http://127.0.0.1:8000
```

Use `--help` for duration, users, spawn rate, rate and output overrides.
Profiles include business hours, 1/5/15-minute spikes, variable demand,
idle/resume, controlled connection storms, slow-query pressure, cache comparison
and continuous failover traffic.

Launch normal Azure profiles through the existing private runner job from an
authenticated operator terminal; the operator does not need a public API endpoint:

```powershell
.\.venv\Scripts\python.exe -m src.experiments.cloud_job --config deployment.local.json --profile expected --confirm-poc
.\.venv\Scripts\python.exe -m src.experiments.cloud_job --config deployment.local.json --profile peak --confirm-poc
.\.venv\Scripts\python.exe -m src.experiments.cloud_job --config deployment.local.json --profile spike-1-minute --confirm-poc
.\.venv\Scripts\python.exe -m src.experiments.cloud_job --config deployment.local.json --profile variable-demand --confirm-poc
```

The launcher preserves the image, resources and secret references, changes only
the requested execution, and waits for that exact execution. Failed or missing
upload receipts fail verification. A receipt is not an independently downloaded
and hash-verified artifact bundle; see [evidence retrieval](docs/evidence-guide.md).

50,000 reads/day is about **0.579 reads/second over 24 hours** or **1.736 over
8 hours**. API requests, SQL calls and logical reads are different quantities.
Accelerated runs must retain the acceleration factor and requested/achieved
throughput. They do not reproduce all real-time cache, idle and autoscaling effects.

Connection storms and deliberately slow queries are disabled unless explicitly
enabled on both the client and server. Only use disposable synthetic targets.
See [spike/throttling guidance](docs/spike-and-throttling-guide.md).

### Scale to 4 vCores, compare, restore

```powershell
.\.venv\Scripts\python.exe -m src.operations.cli scale --config deployment.local.json --vcores 4 --confirm-poc
# Repeat the identical peak/spike profile and retain its hash and measurement window.
.\.venv\Scripts\python.exe -m src.operations.cli scale --config deployment.local.json --vcores 2 --confirm-poc
```

Keep schema, dataset/seed, query/index mode, app image/replicas, cache, region,
profile, duration and monitoring equivalent. Record change-operation times and
exclude or separately label warm-up. Do not interpret a changed dataset/cache as
evidence of a compute-tier benefit.

Write workloads change stock, work items and idempotency state. Use read-only
equivalent runs or an explicitly approved deterministic reset before **each**
comparison run, including the first. From the authorized private administration
context, with writers stopped:

```powershell
.\.venv\Scripts\python.exe -m src.database.manage seed --reset --allow-destructive-tests --confirm-poc --size small --seed 42
```

Retain the reset receipt, original workload settings and before/after dataset
fingerprints. The fingerprint summarizes aggregate state, not every row. Replaying
the same idempotency keys is not an equivalent new-write workload. No reset is
authorized merely by ordinary deployment confirmation.

### Serverless C1 and C2

```powershell
.\.venv\Scripts\python.exe -m src.operations.cli switch-compute-tier --config deployment.local.json --compute-tier Serverless --min-vcores 0.5 --max-vcores 4 --auto-pause-delay -1 --confirm-poc
.\.venv\Scripts\python.exe -m src.experiments.runner --profile variable-demand --host http://127.0.0.1:8000
# Use the private target for Azure measurements; loopback measures only the local app.
.\.venv\Scripts\python.exe -m src.operations.cli switch-compute-tier --config deployment.local.json --compute-tier Serverless --min-vcores 0.5 --max-vcores 4 --auto-pause-delay 60 --confirm-poc
```

For C2, stop SQL readiness probes, dispose pooled connections and stop diagnostic
SQL/background traffic. Poll the **control plane**, not SQL, until genuinely
paused. Measure the first triggering request including retries, then subsequent
requests separately. Failover groups, geo-replication, LTR and DNS aliases can
prevent auto-pause. Never manufacture a pause event from an idle CPU chart.
Follow the [serverless test guide](docs/serverless-test-guide.md) for the guarded
idle/resume runner and the complete comparison matrix.

## Metrics, tuning and cache

- [Metrics catalog](docs/metrics-catalog.md): units, aggregation, windows,
  interpretations and common misinterpretations.
- [Monitoring guide](docs/monitoring-guide.md): Azure Monitor, real KQL tables,
  Query Store/DMVs, portal screenshots to capture and permission boundaries.
- [Workload guide](docs/workload-guide.md): matrix, tuning restoration and cache runs.
- [Cost guide](docs/cost-guide.md): live price inputs and complete cost model.

Use shared UTC windows and run IDs. `app_cpu_billed` totals are **vCore-seconds**;
divide by 3,600 before applying a vCore-hour price. CPU percentage alone neither
proves allocated compute nor exact autoscaling reaction time. Missing series are
unknown, not zero. Alert templates are disabled by default until thresholds,
owners, action groups and runbooks are reviewed.

From an authorized SQL-connected execution context:

```powershell
.\.venv\Scripts\python.exe -m src.database.manage migrate
.\.venv\Scripts\python.exe -m src.database.manage seed --size small --seed 42
.\.venv\Scripts\python.exe -m src.database.manage tune --mode baseline --allow-unsafe-test
.\.venv\Scripts\python.exe -m src.database.manage tune --mode both --allow-unsafe-test
# Run identical traffic before/after, then restore baseline for compute comparisons.
```

The bootstrap job provides the private execution context for initial schema and
user creation. Runtime identity is not a schema administrator. Cache comparisons
must distinguish cold/warm state, hit/miss ratio, staleness policy, invalidation,
SQL-call reduction and total cost. A development memory cache is not evidence
for a multi-replica distributed deployment.

## Availability, DR and recoverability

Run continuous `failover` profile traffic separately while issuing a planned
in-region failover:

```powershell
.\.venv\Scripts\python.exe -m src.operations.cli failover-test --config deployment.local.json --confirm-poc
```

Unsupported SKU/API operations are failures, not simulated successes.
For optional cross-region DR, configure `enable_dr` and a distinct
`secondary_location`, deploy, then use:

```powershell
.\.venv\Scripts\python.exe -m src.operations.cli failover-test --config deployment.local.json --geo --confirm-poc
.\.venv\Scripts\python.exe -m src.operations.cli failover-test --config deployment.local.json --geo --failback --confirm-poc
```

Forced failover additionally requires **both** `--allow-destructive-tests` and
`--allow-data-loss`; it can lose committed data. No forced failover is a default test.
Failover groups provide **one writable primary**, not active/active SQL writes.
Read-only replicas can lag. Database DR does not recreate the application tier.

PITR creates a separately billable database without replacing the source:

```powershell
.\.venv\Scripts\python.exe -m src.operations.cli restore-test --config deployment.local.json --restore-time "<UTC-within-retention>" --confirm-poc
```

Validate rows/constraints against the expected recovery point and delete the
restore database afterward. Control-plane completion is not application RTO or
data-loss RPO. See [availability](docs/availability-guide.md),
[DR](docs/disaster-recovery-guide.md) and [failover testing](docs/failover-test-guide.md).

## Evidence and destruction

Raw local artifacts live under `results/local-untracked-runs/`; cloud jobs
persist raw artifacts in private Blob storage through managed identity. Public
sharing is a separate, fail-closed sanitization/review step.

```powershell
.\.venv\Scripts\python.exe -m src.experiments.sanitize --help
.\.venv\Scripts\python.exe -m src.experiments.scan --help
.\.venv\Scripts\python.exe -m src.operations.cli destroy --config deployment.local.json --confirm-poc --allow-destructive-tests
```

Destruction deletes the dedicated POC resource group and its data. Inspect the
saved inventory first. For only a generated PITR destination, add
`--restore-database "<poc-restore-name>"`. Billing can continue until deletion
completes; backup retention or separately provisioned resources require review.

Bash and PowerShell wrappers in [scripts](scripts/) forward to the same Python
commands. If an organizational PowerShell execution policy blocks scripts, use
the direct Python commands; do not bypass that policy.

## Repository tree

```text
.
├── README.md, LICENSE, SECURITY.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md
├── SUPPORT.md, CHANGELOG.md, threat-model.md, .env.example
├── deployment.example.json
├── .github/workflows/             quality, security and manual OIDC deployment
├── docs/                         customer guides, diagrams, decisions, templates
├── prompts/                      implementation, maintenance and analysis prompts
├── infra/bicep/                   modular secure/evaluation/optional resources
├── src/
│   ├── api/, configuration/       typed endpoints and validated configuration
│   ├── database/                 memory/SQL repositories and management commands
│   ├── resilience/, telemetry/    bounds, retries, breaker and safe telemetry
│   ├── cache/                    cache adapters and invalidation
│   ├── experiments/              runners, matrix, evidence and sanitization
│   └── operations/               guarded Azure operations and validation
├── sql/                          migrations, seed, tuning, diagnostics, Query Store
├── load-tests/                   YAML profiles and Locust workload
├── dashboards/                   KQL, workbook and optional visualization examples
├── tests/                        unit, integration, infrastructure, performance, safety
├── scripts/                      equivalent Bash and PowerShell commands
└── results/                      guidance only; generated runs remain ignored
```

## Limitations and customer inputs

- This POC uses synthetic data. Real workload shape, skew, data growth, SLOs,
  concurrency, staleness and recovery objectives remain **TBD**.
- App compute, connection limits and the load generator can bottleneck before SQL.
  Closed-loop load tests and acceleration have measurement limitations.
- Local tests cannot replace Azure SQL execution-plan, identity and permission tests.
- Secure networking requires an appropriate execution location; this repository
  does not automatically install VPN, ExpressRoute or an operator jump host.
- Production API authentication, business authorization and complete app-tier DR
  require a separate design; do not expose the POC as a production application.
- Product capabilities, quotas, pricing and legacy Redis eligibility change.
  Revalidate in the chosen subscription and region.
- Optional experiments and unavailable tools must be listed as **not executed**,
  not passed. Generated reports explicitly preserve unknown results.

Input files: [workshop](docs/customer-workshop.md), [assumptions](docs/assumptions.md),
[deployment example](deployment.example.json), [.env.example](.env.example),
[profiles](load-tests/profiles/), [results template](docs/results-template.md) and
[executive summary](docs/executive-summary-template.md). Keep filled customer
answers, IDs, redaction lists and actual evidence outside version control.

Original source/examples are synthetic and credential-free. Before every
publication, scan the worktree, staged files, Git history and evidence, and
manually review the sanitization report. The absence of a pattern match does not
prove arbitrary customer prose is safe to publish.
