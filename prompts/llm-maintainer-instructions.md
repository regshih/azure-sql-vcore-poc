# Reusable maintainer instructions

Use these instructions for repository maintenance, code review and documentation
updates. They are not authorization to deploy or operate Azure resources.

---

Inspect README.md, SECURITY.md, architecture, assumptions, relevant ADRs and Git
status before changing this repository. Preserve unrelated work. Explain a
small, complete change and its validation/rollback, then implement it when
authorized. Use current repository commands and supported dependencies rather
than invented paths, flags or APIs.

## Nonnegotiable invariants

- Synthetic data and placeholder-only public source/docs/tests/prompts.
  Customer values stay in ignored local configuration. Never print or commit
  credentials, tokens, connection strings, real cloud names/IDs, private IPs,
  usernames, personal data or private profile paths.
- Secure private SQL/app profile remains default. Evaluation access is explicit
  exact-caller-IP only and temporary. Never add a broad network bypass.
- Passwordless Entra tokens, TLS validation, separate bootstrap/runtime identities
  and least runtime SQL privilege. No default Key Vault or avoidable secret.
- Passwordless applies to SQL/Redis data access, not the optional shared-bearer
  experiment controls. They require externally supplied high-entropy secret,
  approved delivery/rotation and actual-peer network allowlisting. The core
  application does not issue/retrieve the secret. Preserve deployment-generated
  ephemeral ARM secure parameters, encrypted app/runner secret references and
  finally cleanup; redeployment rotates both consumers. Verify actual wiring and
  cleanup without printing secrets; never trust forwarded headers for authorization.
- Keep unsafe workloads disabled and bounded; retain destructive approval flags
  and data-loss warnings. A request to build/test does not authorize deployment,
  scale, failover, restore or destruction.
- Fixed one-replica application controls for experiments; same database/schema/
  data/region/hardware/storage/workload/monitoring where supported across A/B/C.
  Document every deliberate departure from the 15-test matrix.
- Mixed-write comparisons require explicitly approved deterministic synthetic
  reset before each run, or verified equivalent read-only state. Resets require
  `--allow-destructive-tests --confirm-poc` and a checked synthetic POC marker;
  never reset by default or infer approval. Matrix reset also requires
  `--reset-dataset --confirm-no-other-sql-clients --confirm-single-instance`
  plus existing execution/unsafe gates, and repeats before every selected case.
  Keep fingerprints, mutation deltas and create-only initial/final manifests,
  use fresh idempotency namespaces, and reject unsupported fairness claims.
  Preserve per-case reset receipts separately from mutable manifest enrichment.
  Default `non-equivalent-or-unverified` is not changed merely by equal hashes.
  Reset does not restore previous mutated data; configuration cleanup is not
  data recovery. Preserve that acknowledgement, generator hash and final
  snapshot digest binding. Pre/post SQL refresh belongs outside measured UTC
  windows and idle intervals; admission resume must verify the same instance.
  Metadata SELECTs can still warm SQL caches; disclose that observation effect.
  SQL comparisons require fresh verified adapter/version/tuning/dataset_size
  metadata; memory or unverified adapters cannot be SQL evidence. Pass observed
  --product-count explicitly across compared profiles; overflow fails rather
  than silently changing distributions or hashes. Preserve refresh→baseline
  counters→workload→end counters→refresh order, outside measured/idle intervals.
  Require both repository_backend=sql and sql_adapter_configured=true.
  Product bounds apply to product-ID workloads, not department-only slow/storm
  diagnostics; other adapter/authentication/unsafe guards still apply.
- Use the canonical authenticated metadata client for fairness snapshots; no
  token means no metadata HTTP probe, and no legacy anonymous route fallback.
  Preserve the controlled guard's poc_mode=true, poc_marker=sql-vcore,
  environment=poc and required application/synthetic flags; legacy {poc:true}
  alone is not sufficient authorization.
- Cache comparisons use disabled plus the actual configured backend by default.
  Explicit modes and matrix backend assertions must match before any toggle;
  they never switch/provision providers. Preserve latest-version restoration.
- Maintain provisioned 2→4→original and first-class C1/C2. Validate exact current
  serverless capabilities; no unsupported hard-coded fallback.
- Keep local memory cache development-only and optional paid Redis off by default.
  Preserve the exact caveat: “The local in-memory cache is not a production
  distributed-cache design.”
- Default CI does not deploy. Protected environments, OIDC, rulesets and scanning
  settings require explicit owner configuration, not claims based on source files.
- Cloud raw artifacts persist completely to private Blob Storage via managed
  identity when storage settings are configured; any upload failure fails the
  job. Log only file/hash/prefix receipts, not raw contents. Authorized private-
  network downloads must verify inventory and SHA-256 before sanitization.
- Preserve `src.experiments.cloud_job` management-plane execution overrides:
  complete template and identity/storage environment retained, exact returned
  execution polled, persistent job template unchanged, no automatic restart.
  Receipt retrieval is not independent Blob download/hash verification.
  Baseline-image idle/matrix and operator/config-based collector CLI dependencies
  remain explicit. Managed cloud monitoring instead uses CLI-free MI-only REST,
  separate ARM/Log Analytics audiences and mandatory coverage reporting.
  Missing required sources fails nonzero; archive failure evidence without
  promoting it to success. Query Store/SQL diagnostics/pricing require separate
  approved observer/operator collection, never enlarged runner SQL privileges.
  Measured labels cover only the Azure Monitor subset. Preserve request/response/
  retry bounds and disabled redirects; verify rebuilt image/environment/roles
  before treating locally tested collector code as live validation.

## Evidence discipline

Every new default: “POC assumption, not a confirmed customer requirement.”
Every unknown customer objective: “TBD.”
Every unmeasured/undemonstrated result: “Not demonstrated by this POC run.”

Separate measured facts, estimates, official product behavior, guidance,
recommendations and unknowns. Do not make cloud claims from mocked tests. Do not
rename timeouts as throttling without correlated error/resource evidence.
Never average percentiles or compare unmatched profiles as a capacity experiment.
Use actual achieved demand and distinguish API requests from SQL statements.

Serverless is bounded autoscaling, not burst credits or a universal spike/cost
solution. Use Total app_cpu_billed, account for memory/minimums, and do not infer
allocated vCores solely from CPU%. C2 requires genuine no-session idle periods,
control-plane pause proof and separate first/subsequent request latency.
Availability is not DR; asynchronous failover groups have one writer, and
RTO/RPO require client and data-consistency evidence.
The optional deployed DR topology protects SQL only; the app remains regional.
Do not relabel authenticated public ACR Basic or public SDK telemetry ingestion
as private endpoints. Account for Blob lifecycle plus soft-delete retention costs.

Use only current official Microsoft references for product claims. Inspect real
workspace schemas. Avoid stale Redis retirement timelines: check the latest
updates, including removal of the existing-customer October 2026 creation block.
Retail rates remain dynamic and dated with region/currency/meter/units. Never
select a cost winner without complete inputs.

## Completion criteria

Update relevant tests/docs/ADRs. Run the smallest meaningful validation first,
then repository-required checks. Report exact failed/unavailable/unexecuted
commands without disguising them as passing. Sanitize evidence to a separate
destination; scan worktree, index, history and generated bundles; manually
review final public artifacts. Report changes, validation, limitations and
remaining customer inputs. Do not commit or deploy without explicit instruction.
