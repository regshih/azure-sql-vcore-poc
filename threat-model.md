# Design threat model

This document describes design risks and controls. It is not a vulnerability hunt,
penetration-test result or security certification. Control effectiveness in a
deployed environment: **Not demonstrated by this POC run.**

## Scope, assets, and boundaries

Assets include source and dependencies; build image; deployment permissions;
bootstrap/runtime/diagnostic identities; SQL schema/data; API availability;
telemetry; raw evidence; sanitized releases; and the customer's cloud budget.
Only synthetic data is permitted. Customer objectives/policies are **TBD**.

Trust boundaries:

1. Public source and PR input → maintainer/CI execution.
2. Operator local configuration → Azure control plane.
3. Client/runner → restricted API ingress.
4. API runtime identity → private SQL data plane.
5. Bootstrap/diagnostic identity → privileged SQL/control operations.
6. App/platform logs → private workspace → sanitizer → public artifact.
7. Primary region → optional asynchronous DR secondary/listeners.

See [diagrams](docs/architecture-diagram.md). External dependencies, Azure service
internals and a production end-user authorization design are outside the default
POC's verification scope.

## Risk and control table

| Design risk | Prevention/detection intent | Residual risk and validation needed |
| --- | --- | --- |
| Untrusted PR executes privileged workflow | CI nondeploying by default; least permissions; no customer secrets; owner-reviewed actions | Owners must configure rulesets, reviewers and workflow protections |
| Supply-chain compromise | Reviewed dependency bounds/lock workflow, audit tools, image provenance and updates | Scanner success is not proof of no vulnerable dependency; assess findings and unsupported platforms |
| Wrong account/scope deployment | Explicit local config, scope checks, confirm-PoC gate, dedicated disposable scope | Operator error remains possible; verify privately before changes |
| Runtime identity has admin rights | Separate bootstrap/admin and least-privilege runtime contained user | Verify actual grants and identity selection; inherited cloud access can violate intent |
| Public API/SQL exposure | Private default; exact-caller-IP evaluation gate; no broad bypass | Network restriction is not user authentication; production auth is separate |
| Token/credential leakage | Passwordless SQL/Redis data access, no token printing, redacted telemetry; optional bearer secret delivered privately | Optional controls are not secretless; SDK/driver exceptions or export metadata can leak identifiers; inspect actual output |
| Misuse of optional experiment controls | Externally supplied high-entropy bearer secret, constant-time comparison, actual-peer network allowlist, POC/unsafe gates | App does not provision/issue/retrieve secret; shared-secret rotation and cloud delivery must be verified; forwarded headers are not authorization |
| Deployment control token leaks during provisioning | Cryptographic ephemeral generation, ARM secure parameter, encrypted app/runner secret references, no value output, single-use file removed in finally | Inspect permissions and cleanup after abrupt termination; redeployment must rotate both consumers without exposing the value |
| Supporting-service network exposure misunderstood | ACR Basic authenticated public endpoint with anonymous/admin disabled; public SDK telemetry ingestion with private query authorization | Private SQL/API/Blob does not imply private ACR or private ingestion; review egress policy and Premium/private alternatives |
| SQL injection/unbounded queries | Parameterization, validation, bounded pagination, disabled inefficient endpoint | Review new query paths and diagnostics; synthetic data does not remove injection risk |
| Duplicate or uncertain writes | Transactions, stable idempotency key, bounded safe retries | Network loss around commit needs live SQL readback tests |
| Retry amplification and denial of service | Bounded concurrency/pool/deadline, budget, jitter, circuit and load shedding | Defaults may not fit real demand; measure saturation and recovery |
| Unsafe workload reaches production | Explicit unsafe flag, disposable target checks, upper bounds | Flags are not authorization; operator must approve scope |
| Incorrect cache disclosure/stale state | Off by default; cache only approved read endpoints; document consistency | Process-local invalidation is not distributed correctness |
| Tampered/misleading evidence | Version/hash/window provenance, preserved private raw source, separated estimates | Hashes detect mismatch but are not signed provenance or configured storage immutability |
| Cloud job exits before artifacts persist | Mandatory full-file Blob upload when configured; fail job on upload error; inventory/SHA-256 receipt | Verify actual blobs and receipt on authorized private-network download; partial uploads remain incomplete |
| Evidence storage exfiltration or overprivilege | Private Blob endpoint/DNS, no keys/public access, scoped runner write role, separate operator read role | Raw metadata remains sensitive; review retention, inherited permissions and sanitized release boundary |
| Public artifact contains identifiers | Structured allowlisting/redaction, history/index/worktree scan, manual review | Customer names may evade regex; archives/images need special review |
| Destructive failover/data loss | Planned by default, forced-operation data-loss warning and explicit destructive flags | Async geo-replication may lose acknowledged writes during forced promotion |
| DR unavailable despite replicated SQL | Private DNS/identity/app recovery for both regions and listener testing | Database failover does not recreate app/network or meet RTO automatically |
| Auto-pause disabled by hidden activity | Process-only health, controlled readiness/pools, control-plane idle observation | Third-party jobs and feature exclusions can still prevent pause |
| Cost overrun | Baseline first, optional paid features off, tags/budget, cleanup runbook | Budgets are not guaranteed spending caps; retained resources/logs still charge |

## Least-privilege and data handling

Runtime should only read/write the tables/columns required by the API. Schema
changes, seed, grants and performance-state diagnostics use separate identities.
Private endpoints do not remove authentication/TLS requirements. No Key Vault is
deployed: Container Apps encrypted references hold the generated control token;
infrastructure internally resolves the Log Analytics key without output.
These secrets require reviewed handling and verified wiring. Do not describe the
full controlled-experiment workflow as secretless. The optional DR module is
SQL-only; it does not protect the regional app from a region-wide loss.

Raw logs/results may contain sensitive **environment metadata** despite synthetic
records. Keep them private and ignored. Do not export raw SQL text, parameters,
auth headers, caller claims, endpoints or profile paths.

## Validation and change review

For each material change, identify touched boundaries, new permissions/data,
abuse cases, failure behavior and rollback. Run relevant unit/integration tests
and scan source/artifacts. Live verification requires explicitly approved POC
resources; local mocks do not establish network, identity, database or failover
control effectiveness.

Record an owner placeholder and acceptance decision privately for residual risks.
Revisit this model when adding end-user auth, more replicas, distributed cache,
background jobs, new data types, public ingress, DR or new deployment workflows.
Report sensitive issues privately under [SECURITY](SECURITY.md).
