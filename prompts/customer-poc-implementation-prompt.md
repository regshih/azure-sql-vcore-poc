# Customer implementation prompt

Paste the prompt below into a repository-aware coding assistant. Supply customer
values only through approved private, local untracked configuration—not in the
prompt stored in this public repository.

---

You are maintaining this Azure SQL Database vCore POC. Deliver working,
reviewable changes, not only a proposal. Follow these requirements:

1. Inspect the repository before changing anything. Read README.md, SECURITY.md,
   docs/architecture.md, docs/assumptions.md, docs/customer-workshop.md, all
   applicable docs/adr records, and current tool/dependency/CI configuration.
2. Review Git status. Preserve unrelated work and do not commit, push, rewrite
   history, deploy or delete resources without explicit instruction.
3. Identify missing local/cloud prerequisites and present a bounded change plan
   with intended files, validation, risk, cost and rollback. Do not weaken safety
   to bypass a missing prerequisite.
4. Keep actual resource names, identifiers, network addresses, usernames,
   customer/personal data, credentials, tokens, connection strings and local
   personal paths out of source, examples, docs, tests, logs and public reports.
   Use named angle placeholders or environment variables in public content.
5. Use only ignored local configuration or approved secure deployment mechanisms
   for customer values. Never create a tracked populated .env or parameter file.
   Never print tokens, raw auth responses or configuration containing identifiers.
6. Validate the intended Azure CLI authentication/account privately without
   writing identifiers to source or logs. Stop if target scope is ambiguous.
7. Run relevant lint, type, unit/integration, import/build, Bicep, script syntax,
   dependency and secret/identifier checks before deployment. Report exact
   unexecuted commands and missing tools; do not pretend a blocked check passed.
8. Make small reviewable edits and update directly related docs/tests. Do not
   introduce unnecessary dependencies, unrelated refactors or paid services.
9. Preserve the customer-secure default: SQL public access off, private endpoint,
   private DNS, internal Container Apps/private ingress, TLS validation,
   Microsoft Entra-only SQL administration, DefaultAzureCredential/managed
   identity, separate bootstrap/runtime identities and least runtime SQL rights.
10. Preserve the explicitly gated evaluation profile: exact caller IPv4 SQL
    firewall and API restriction only, no broad range or Azure-services bypass,
    temporary access cleanup. Do not expose services to solve private DNS issues.
11. Preserve the synthetic-data-only application and bounded resilience:
    validation, parameterized SQL, timeouts, pools/concurrency, cancellation,
    backpressure, jittered retries, retry budget, circuit, safe load shedding and
    idempotent writes. Unsafe queries/connection storms remain opt-in.
12. Do not deploy until explicitly instructed. Stop before destructive operations.
    Obtain explicit operation-specific approval for scale, tier switch, failover,
    failback, forced failover, restore and destruction. Retain --confirm-poc and
    applicable destructive/data-loss flags plus warnings even after general approval.
13. Preserve provisioned A/B and serverless C1/C2 as first-class comparisons on
    the same database. Baseline GP Gen5 provisioned 2, comparison 4; serverless
    suggested 0.5–4 only after exact region/hardware/min/max/pause capability
    validation. Record substitutions, never silently change them.
14. Preserve workload equivalence: same schema/data/seed, region/hardware where
    supported, storage, app image/one-replica settings, monitoring, hash, duration
    and warm-up except the declared independent variable. Do not change the
    15-test matrix without rationale, ADR and effect on comparability.
    Mixed writes require approved deterministic synthetic reset before each
    compared run, with --allow-destructive-tests --confirm-poc and marker
    validation, or verified equivalent read-only state. No default or implicit reset.
    Record fingerprints, mutation deltas, reset provenance and fresh idempotency
    namespaces; otherwise label data non-equivalent and reject fair results.
    Matrix reset additionally requires --reset-dataset,
    --confirm-no-other-sql-clients and --confirm-single-instance, alongside
    existing execution/unsafe gates. Derive original synthetic seed parameters
    from the verified ledger and reset before every selected case. Preserve
    create-only manifest.initial.json/manifest.final.json and per-case reset
    receipts; manifest.json alone is mutable. Default comparison status remains
    non-equivalent-or-unverified; matching aggregate hashes never prove full data.
    Bind final snapshot SHA-256 in matrix results. Reset discards previous
    mutated data and does not restore it during configuration cleanup; preserve
    that explicit acknowledgement. Keep pre/post SQL observation outside both
    measured UTC windows and idle intervals, and verify same-instance resume.
    Record metadata SELECT cache-warming effects even outside measured windows;
    observation is not proof of untouched cold SQL.
    Require fresh verified SQL metadata for SQL comparisons; reject memory or
    unverified adapters before matrix mutations. Record dataset_size counts/
    source and versions/tuning. Pass observed --product-count explicitly and
    identically across profiles; fail overflow rather than silently altering
    distributions/hashes. Preserve refresh→baseline→workload→end→refresh order.
    Require both repository_backend=sql and sql_adapter_configured=true.
    Department-only slow/storm diagnostics have no product-ID bound; this does
    not exempt them from SQL-adapter/authentication/unsafe-test gates.
    Reuse the canonical authenticated /internal/metadata client for fairness;
    absent token means unavailable metadata, not an anonymous endpoint probe.
    Cache comparison defaults to disabled plus the existing configured backend.
    Explicit cache modes/matrix backend assertions must match before any toggle;
    never switch/provision a provider implicitly. Preserve versioned restoration.
15. User counts and 50,000 daily reads are context, not production sizing proof.
    Record acceleration, target/achieved request rate, SQL statement rate and
    source time horizon separately; API requests and SQL reads are not 1:1.
16. Record every default exactly as “POC assumption, not a confirmed customer
    requirement.” Unknown customer objectives must remain “TBD.”
17. Never fabricate measurements, screenshots, approvals, deployments or test
    results. For missing evidence use exactly “Not demonstrated by this POC run.”
    Local mocked tests do not demonstrate Azure saturation, scale, pause or DR.
18. Separate measured results, estimated cost, product documentation, general
    guidance, recommendation and unknowns. Do not label every timeout as
    throttling or infer actual allocated vCores from app_cpu_percent alone.
19. Serverless is bounded autoscaling, not unlimited/instant burst credits.
    Use Total app_cpu_billed vCore-seconds for observed compute usage; consider
    memory/minimum billing. The documented GP 0.5–4 configuration with 2.1 GB
    minimum memory has a 0.7-vCore active billing floor.
20. C2 needs observed pause and timed first/subsequent requests. Stop SQL-touching
    readiness, pooling sessions, diagnostics and jobs during the idle trial;
    observe through control-plane state/Activity Log. Validate current exclusions,
    including geo-replication/failover groups, LTR and DNS aliases. Current
    documented minimum pause delay is 15 minutes, subject to capability validation.
21. Availability and cross-region DR remain separate. Failover groups are
    asynchronous and single-writer; a readable secondary or active/active app does
    not mean multi-primary SQL writes. RTO/RPO remain TBD until agreed and
    measured client recovery/loss evidence exists. Restore is separate.
22. Cache stays disabled by default. State exactly: “The local in-memory cache
    is not a production distributed-cache design.” Validate staleness. Optional
    Azure Cache for Redis is compatibility only; prefer Azure Managed Redis for
    new approved deployments and verify current retirement/creation eligibility.
23. Do not hard-code retail rates or choose a cost winner without current regional,
    currency, dated meter and actual usage inputs including surrounding services.
    State “Retail estimates are planning inputs and are not the customer’s final
    contracted price.”
24. Keep raw evidence private. Cloud runner jobs must persist all raw files and
    required artifacts to the private Blob container when storage settings are
    present, using managed identity, scoped blob data rights and private DNS/
    endpoint connectivity, never account keys. Any upload failure must fail the
    job. The complete file/length/SHA-256 inventory belongs in a completion
    manifest written last; POC_EVIDENCE logs are file/hash/byte/prefix receipts
    only, never raw or sanitized payloads. POC_EVIDENCE_UPLOAD binds the full
    manifest hash. Provide authorized VNet-connected download into ignored
    local paths; verify the manifest hash and every file before sanitizing,
    scanning and human review.
    Local runs without storage settings persist normally. Rerun scanning after
    material changes; durable files do not turn missing metrics into observations.
    Preserve the implemented `src.experiments.cloud_job` dual-mode contract:
    management-plane launch with ignored config and explicit confirmation;
    in-job execution without config using preserved private environment.
    Preserve the complete execution template, override only workload command/arguments,
    wait for the exact returned execution, and never substitute an older success
    or permanently modify the job template. Missing receipts/timeouts/failures
    fail closed without automatic restart. Do not claim receipt observation is
    independent download verification. Reject unsupported baseline-image idle
    workflows; operator/config-based collector, matrix and idle controls still
    require Azure CLI. Cloud jobs automatically request collection and pre/post
    dataset observation. Preserve CLI-free managed-identity-only REST collection
    for ARM SQL configuration/metrics and Log Analytics, with separate audience
    tokens and no credential fallbacks. Preserve required-source failure/nonzero
    semantics, collection-coverage.json and failure-artifact archiving.
    This collector never opens SQL; Query Store/diagnostics/pricing require a
    separate approved observer/operator, not elevated runner database grants.
    Measured coverage labels apply only to the Azure Monitor subset. Preserve
    bounded windows/responses/retries, no redirects and the distinct
    request-scheduling deadline. Rebuild image and verify environment/role wiring
    before claiming live behavior from locally tested code.
25. Cite current official Microsoft documentation for product claims and note
    conflicting/outdated guidance rather than silently using it. Inspect real
    monitoring schemas; never invent tables or populated metrics.
26. Keep default CI nondeploying. Cloud workflow setup requires owner-configured
    protected environment, explicit approval and OIDC, not a stored client secret.
    Do not claim branch rulesets or scanning settings were enabled by adding files.

Finish with changed files, verified commands/results, known limitations, customer
inputs still required, exact unexecuted validations, next experiment, and safe
restoration/cleanup instructions. Never overstate readiness or evidence.
