# ADR 0001: Controlled vCore comparisons

**Status:** Accepted for POC design; production choice TBD.

## Context

The scenario provides user counts, approximate daily reads and sub-5-GB data, but
not peak rate, query cost, latency objectives, idle hours or budget. None justifies
a production SKU by itself.

## Decision

Start with Azure SQL Database GP Gen5 provisioned 2 vCores and a 5-GB cap as a
**POC assumption, not a confirmed customer requirement.** Scale the same database
to 4 and restore it. Switch the same database to supported serverless C1/C2,
suggested minimum 0.5 / maximum 4, with exact capabilities validation. Preserve
schema/data/seed, storage, region/hardware where supported, app one-replica
configuration, workload hashes, duration, warm-up and monitoring.

For mixed-write comparisons, require explicitly approved deterministic
synthetic-only reset before each run, with both destructive and POC confirmation
gates and marker validation, or use verified equivalent read-only state.
Preserve fingerprints, mutation deltas, reset provenance and fresh idempotency
namespaces. Same seed is not sufficient after mutation; otherwise the comparison
must be labeled non-equivalent. Reset is never an automatic default.
The matrix's explicit guarded reset derives seed parameters from the verified
ledger and runs before every selected case. Preserve create-only initial/final
manifests and each reset receipt separately from mutable progress enrichment.
Default `non-equivalent-or-unverified` cannot be upgraded from matching aggregate
hashes alone; per-case reset does not automatically establish subrun equivalence.

C1 isolates variable compute from resume; C2 tests genuine idle and first-request
behavior. Query/index/cache changes are separate independent variables.
Business Critical is opt-in after evidence; Hyperscale is not default.

## Alternatives and consequences

Separate databases can simplify concurrent testing but confound data/cache/state
and add cost. A production-sized baseline would invent requirements. One small
app replica helps repeatability but is not production HA or proof the app tier is
never the bottleneck. Scale/tier switches can interrupt clients; record and
restore all settings.

## Validation

Use the [matrix](../test-matrix.md), manifests and correlated telemetry.
Capacity improvement/cost benefit: **Not demonstrated by this POC run.**
