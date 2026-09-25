# Required 15-test matrix

This table specifies the required experiments. It does not assert that they have
run. Every missing result is **Not demonstrated by this POC run.** Rates,
duration and compute defaults are a **POC assumption, not a confirmed customer
requirement.** Customer acceptance criteria are **TBD**.

| Test | Configuration | Workload / changed variable | Proof required | Current result |
| --- | --- | --- | --- | --- |
| 1 | GP provisioned 2 | Expected | Achieved volume/rate, latency/outcomes, SQL/app headroom | Not demonstrated by this POC run. |
| 2 | GP provisioned 2 | Business-hours concentrated | Profile phases/acceleration and correlated telemetry | Not demonstrated by this POC run. |
| 3 | GP provisioned 2 | Peak | Sustained demand, resource/pool/workers/session pressure | Not demonstrated by this POC run. |
| 4 | GP provisioned 2 | Spike | Baseline/ramp/spike/recovery and classified outcomes | Not demonstrated by this POC run. |
| 5 | Same DB GP provisioned 4 | Exact Test 3 peak hash/settings | Scale operation plus comparable steady-state delta | Not demonstrated by this POC run. |
| 6 | Same DB GP provisioned 4 | Exact Test 4 spike hash/settings | Same spike, capacity-only change, recovery comparison | Not demonstrated by this POC run. |
| 7 | Restored GP provisioned 2 | Tuned query/index, repeat relevant workload | Actual index/plan change, CPU/reads/duration, API effects | Not demonstrated by this POC run. |
| 8 | GP provisioned 2 | Configured cache backend enabled, repeat relevant workload | Hit/miss, SQL calls avoided, cold/warm latency and staleness | Not demonstrated by this POC run. |
| 9 | Same DB GP serverless C1 | Expected, pause disabled | Validated bounds, utilization, billed compute and client outcomes | Not demonstrated by this POC run. |
| 10 | Same DB GP serverless C1 | Variable demand | Phase response, variability, near-ceiling proxy, billed compute | Not demonstrated by this POC run. |
| 11 | Same DB GP serverless C1 | Exact comparable spike | Ceiling context, latency/retry/timeout and recovery | Not demonstrated by this POC run. |
| 12 | Same DB GP serverless C2 | Idle and resume | Observed Paused/Online transitions, first/subsequent latency | Not demonstrated by this POC run. |
| 13 | Same DB GP serverless C2 | Business-hours then genuine idle | Source pattern and real idle/paused duration, remaining costs | Not demonstrated by this POC run. |
| 14 | Restored provisioned baseline | Approved planned availability/failover, low continuous traffic | Operation, bounded retries, stable client recovery, integrity | Not demonstrated by this POC run. |
| 15 | Optional failover group | Approved planned geo-failover | Roles/listeners, lag/loss, client recovery, failback | Not demonstrated by this POC run. |

Tests 14/15 require separate explicit operational approval. Optional forced
failover is not silently part of Test 15. C2 is ineligible with some required
features; a blocked configuration is not a successful test.

The standard matrix targets **General Purpose only**. The optional provisioned
Business Critical configuration is a separately approved extension, not another
standard row or a supported serverless tier. Validate its regional capability
and design a separate comparison before enabling it.
Require verified fresh SQL metadata before execution; memory/unverified adapters
are rejected before matrix control-plane mutations. Both
`repository_backend=sql` and `sql_adapter_configured=true` are required.
Record the actual
`dataset_size` counts/source, schema/dataset versions and tuning mode.

## Invariants and restoration

Same database, data/seed/skew/schema, region/hardware where supported, storage,
monitoring, app image/configuration/one replica, warm-up, duration and workload
hash must remain fixed except the named change. Record deviations rather than
calling them controlled comparisons. Restore original provisioning, index/query,
cache, probe and unsafe-test settings between isolated experiments.

Write-mix rows mutate inventory/work items. Fairness review requires an explicitly
approved synthetic-only deterministic reset before each comparable run, or
independently verified equivalent read-only state. The matrix **never resets by
default** and defaults to `non-equivalent-or-unverified`. Equal profile hashes
or aggregate fingerprints never authorize an automated fair-comparison claim.
Reset requires all the additional gates documented below, not merely ordinary
matrix execution approval.
Record dataset fingerprints, count/write deltas, reset provenance and preserved
per-run manifests. Fresh idempotency namespaces are required; replayed writes
do not represent the same new-write workload. If reset/equivalence is not
established, mark the comparison non-equivalent and do not claim a fair result.
See [dataset-state equivalence](workload-guide.md#dataset-state-equivalence).

Reset-command approval applies before every mixed-write run, including the first.
Use the guarded core `seed --reset` command under an approved administrative
identity after stopping writers and draining the app pool; preserve reset JSON
manifests. Never construct independent deletion SQL or auto-enable reset from
the matrix's general execution confirmation.
When matrix reset is explicitly enabled, it repeats before **every selected
case**, including the first and read-only cases. Review that full reset scope
before approval.

Current `dataset_state_fingerprint` has scope
`aggregate_state_not_full_content`: matching aggregate hashes are not proof that
every row is identical. Preserve the deterministic reset manifest and live
`dataset_state` before each run; disclose the aggregate-only limitation. Do not
use seed-ledger counts as current post-workload row counts. An untagged database
fails the reset guard and must not be silently relabeled synthetic.
Require `status=reset_and_seeded` from every approved reset, not `already_seeded`.
Abort the claimed equivalent comparison when the reset or manifest validation
fails. Refresh live aggregate metadata only after maintenance resume and before
the workload baseline, with other writers stopped.

For Tests 7/8 identify the reference test explicitly. Do not compare a warm cached
run with an unrelated cold run or change query tuning and capacity simultaneously.
Use repeated runs and disclose variance instead of selecting the most favorable
sample.

## Per-test collection checklist

- Run ID; region; tier; hardware; provisioned capacity or serverless minimum,
  maximum, memory and pause setting; storage; zone and backup redundancy.
- UTC start/end; versions; dataset actual size; profile hash and overrides;
  source horizon/acceleration; warm-up and recovery boundaries.
- Before/after dataset fingerprints, mutation counters, reset approval/provenance
  or verified read-only equivalence, and run-specific idempotency namespace.
- Create-only `manifest.initial.json` and `manifest.final.json` snapshots;
  per-case `reset-provenance-test-NN.json` at the matrix root when reset is used.
- Requests, successes, failures, retried requests, retry attempts, timeouts,
  shed counts, completed operations, achieved throughput, p50/p95/p99.
- Maximum/mean CPU, data/log I/O, workers/sessions; failed connections/deadlocks;
  pool utilization/waits; cache hits/misses/staleness where relevant.
- Serverless state/events, active/idle/paused duration, app CPU/memory and
  billed Total with coverage where applicable.
- Query Store/plan/wait evidence, safe classified errors and cost inputs.
- Notes, anomalies, missing evidence, operational restoration and cleanup.

Use the matrix wrapper's help to inspect automatic execution versus manual gates.
The ability to construct a matrix row is not proof of cloud execution. See
[workload guide](workload-guide.md), [evidence](evidence-guide.md) and
[results template](results-template.md).

## Matrix command and approvals

Without `--execute`, the matrix command describes planned rows rather than
changing resources:

```powershell
.\.venv\Scripts\python.exe -m src.experiments.matrix
```

In plan mode, `--output` selects a JSON **file**; during execution it selects a
run **directory**. Use a new ignored private destination in either case.

Execution requires `--execute --confirm-poc --allow-unsafe-test`, a private
`--config`, `--host`/remote `--allow-host`, a new `--output` directory,
`--original-tuning` matching the observed starting state, and a supported
positive `--auto-pause-delay`. Use `--tests` to select only specifically approved
rows. C2 also needs `--confirm-no-other-sql-clients` and an adequate
`--pause-timeout`; Test 15 additionally needs `--include-geo`.

### Optional guarded dataset reset

Reset requires **all** of `--reset-dataset --allow-destructive-tests --confirm-poc
--confirm-no-other-sql-clients --confirm-single-instance`, in addition to normal
execution gates including `--execute --allow-unsafe-test`. No flag is inferred
from another. Verify the singleton app, stop other SQL clients/writers, and
approve an administrative SQL identity plus private connectivity.

The matrix derives the original synthetic seed, size and row count from the
verified refreshed ledger and records the generator hash, rather than assuming
the default seed. It checks
application and database synthetic markers, drains the singleton, invokes
the admin-only guarded core reset, verifies same-instance admission restoration
in a `finally` path and verifies the post-reset aggregate state.
Failed reset, marker/ledger checks or
state validation cannot produce a successful equivalent case. A cleanup resume
after failure is not permission to continue the workload.

**Reset discards the previous mutated synthetic data.** It rebuilds the approved
deterministic seed; it does not preserve or later restore that previous live
content. Configuration/tuning/cache cleanup remains separate and cannot undo
the data reset. Approve this loss explicitly before selecting reset.

The matrix accepts `--product-count` and `--write-ratio`; record both overrides.
Explicitly set product count to the verified seeded count, identically across
compared cases. Product-ID distributions exceeding that observed count fail rather
than silently changing the profile/hash. This guard also applies without reset.
Department-only diagnostic work does not select product IDs and is exempt from
that distribution bound, not from verified SQL-adapter requirements.
The following is an opt-in command template, **not permission to reset**:

```powershell
.\.venv\Scripts\python.exe -m src.experiments.matrix --execute --confirm-poc --allow-unsafe-test --config <local-config-path> --host <base-url> --allow-host <base-url> --output results\local-untracked-runs\<matrix-id> --original-tuning <observed-original-tuning> --auto-pause-delay <validated-auto-pause-minutes> --tests 1 3 5 --reset-dataset --allow-destructive-tests --confirm-no-other-sql-clients --confirm-single-instance --product-count <seeded-product-count> --write-ratio <approved-write-ratio>
```

Selection 1/3/5 is illustrative: approve the actual cases and associated compute
changes explicitly. Reset provenance, aggregate checks, fixed workload controls
and human review support comparison assessment; they do not turn an
aggregate-only fingerprint into full-content proof.
If a selected case produces multiple compared subruns, verify reset/read-only
equivalence at each actual comparison boundary. A single case-level reset does
not establish equal starting data for all subsequent write-mix subruns.

### Observations and immutable run snapshots

The matrix enables refreshed pre/post dataset observation automatically, outside
both idle intervals and the measured workload UTC window. Standalone runs opt
in with `--observe-dataset-state`. These refreshes perform SQL and require the
protected endpoint credentials/network
path; never collect them during a no-session pause observation.
Metadata SELECTs can warm SQL caches outside the measured window. Preserve the
recorded limitation, apply the same observation/warm-up order and do not label
an observed baseline as untouched cold SQL.

Each run preserves create-only `manifest.initial.json` and
`manifest.final.json` containing the relevant before/after state and fingerprint
scope, process-counter deltas, reset provenance and unique idempotency namespace.
The matrix root retains each `reset-provenance-test-NN.json`. Existing
`manifest.json` remains the mutable progress/enrichment view, not a substitute
for the original snapshots. Matrix results bind the final snapshot's SHA-256;
verify that digest against the preserved file. Paired verified resets still do
not produce a blanket automated fairness claim. Create-only application behavior
is not a storage WORM/retention guarantee. See the
[artifact contract](evidence-guide.md#artifact-contract).

### Original settings and restoration

`--original-tuning` is an operator assertion; record independently observed
starting tuning and restored objects/plans. The authenticated explicit metadata
refresh exposes `tuning_mode` from the database's runtime configuration. Capture
it before any tuning change and before metrics baseline; a null/unknown value
requires an explicit reviewed original-mode assertion or abort, never an assumed
baseline. Preserve original SKU, hardware family and full supported compute
configuration, and restore that exact configuration in the cleanup path rather
than blindly selecting the default 2-vCore setting. Matrix output includes
`serverless-comparison.md` and `failover-application.json` when applicable.
The latter's sampled five-consecutive-success recovery criterion is a declared
POC heuristic, not proof of customer RTO or sustained latency compliance.

The matrix can invoke capacity/tier/tuning/cache and approved failover operations.
Do not execute all rows merely to preview a plan. Confirm operation-specific
approval for the selected rows, control-token/network prerequisites, optional
feature availability and restoration first. Test 8 uses the **configured
backend**, comparing disabled versus that existing provider. It has no hard-coded
memory default. Optional `--cache-backend memory` or `--cache-backend redis`
asserts the existing backend; it does not select, switch or provision one.
A mismatch is rejected before the first toggle. Memory remains development-only;
cloud runs must not bypass that restriction. An existing approved Redis backend
is used automatically. If the required cloud backend is unavailable, report the
row as blocked/unexecuted rather than provisioning a paid cache implicitly.
Preserve GET-version → confirmed PUT → latest-version restoration.
A cloud Redis comparison requires separate resource/cost/identity approval.
The reset flag `--allow-destructive-tests` does not authorize forced failover.
The matrix does not accept `--allow-data-loss`. Use the separately approved
forced-failover operation only when explicitly authorized; never reinterpret a
planned matrix row as permission for forced failover.
