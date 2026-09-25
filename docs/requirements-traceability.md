# Specification traceability and proof checklist

This maps the original 31-section specification to repository documentation and
intended implementation/validation locations. A path below is an ownership/
inspection target, **not** an assertion that its implementation or live behavior
passed. Use actual validation outputs and manifests to establish status.
Unknown customer inputs are **TBD**; defaults are a **POC assumption, not a
confirmed customer requirement.**

| Section | Requirement | Documentation / implementation inspection targets | Proof still required |
| --- | --- | --- | --- |
| 1 | Scenario and sizing inputs | [Workshop](customer-workshop.md), [assumptions](assumptions.md), [workloads](workload-guide.md) | Approved objectives and representative workload; capacity: Not demonstrated by this POC run. |
| 2 | Evidence-based POC objectives | [Results](results-template.md), [matrix](test-matrix.md), experiments/tests | Complete correlated runs; outcomes: Not demonstrated by this POC run. |
| 3 | Provisioned A/B, serverless C, optional D | [Architecture](architecture.md), [deployment](deployment-guide.md), infrastructure modules/operations | Exact capabilities, deployed settings and restoration: Not demonstrated by this POC run. |
| 4 | Fair provisioned/serverless strategy | [Comparison](provisioned-vs-serverless.md), [C1/C2](serverless-test-guide.md), matrix/profile manifests | Same-variable controls and repeatability: Not demonstrated by this POC run. |
| 5 | Stack/tooling | [Architecture](architecture.md), [contribution checks](../CONTRIBUTING.md), manifest/CI | Local build/import/lint/test outputs and explicit unavailable tools; cloud stack: Not demonstrated by this POC run. |
| 6 | Synthetic model/API/migrations/tuning | [Workloads](workload-guide.md), API/database source, SQL migrations/tuning | Actual SQL semantics, seed limits, plans and write safety: Not demonstrated by this POC run. |
| 7 | Required workload profiles | [Profile catalog](workload-guide.md), load-test profiles and runner | Every profile's achieved shape/volume/flags: Not demonstrated by this POC run. |
| 8 | Outcome taxonomy | [Spike guide](spike-and-throttling-guide.md), experiments/resilience/telemetry | Correlated failure/attempt metadata and classifications: Not demonstrated by this POC run. |
| 9 | Resilience and tests | [Spike guide](spike-and-throttling-guide.md), [ADR 0004](adr/0004-bounded-resilience-and-cache.md), resilience/tests | Unit paths plus live bounded recovery/idempotency: Not demonstrated by this POC run. |
| 10 | Optional caching | [Cache](workload-guide.md#cache-comparison), cache source/optional infrastructure | Hit/miss, avoided calls, expiry/staleness and distributed limits: Not demonstrated by this POC run. |
| 11 | Monitoring model/catalog | [Metrics](metrics-catalog.md), telemetry/collector | Source mappings, tags, units, coverage and export validation: Not demonstrated by this POC run. |
| 12 | Portal monitoring navigation | [Monitoring](monitoring-guide.md) | Placeholder-only instructions supplied; live portal observations: Not demonstrated by this POC run. |
| 13 | SQL views/Query Store scripts | [Diagnostic catalog](metrics-catalog.md#diagnostic-and-query-store-interpretation), SQL diagnostics/query-store | Script permissions/output/retention and real execution: Not demonstrated by this POC run. |
| 14 | Azure Monitor Logs | [Schema-first KQL](monitoring-guide.md#logs-schema-first), dashboards/diagnostic settings | Actual workspace tables/categories/schema and query execution: Not demonstrated by this POC run. |
| 15 | Disabled configurable alerts | [Alerts](alerting-guide.md), monitoring infrastructure | Supported signals, thresholds, owners/routing and noise review: Not demonstrated by this POC run. |
| 16 | Fifteen-test matrix | [Matrix](test-matrix.md), experiments/matrix | Actual rows executed with all required fields: Not demonstrated by this POC run. |
| 17 | Serverless decision report | [Decision report](serverless-decision-guide.md), analysis prompt | Idle/resume/ceiling/billing/predictability evidence: Not demonstrated by this POC run. |
| 18 | In-region availability | [Availability](availability-guide.md) | Supported configuration, client recovery and integrity: Not demonstrated by this POC run. |
| 19 | Cross-region DR and restore | [DR](disaster-recovery-guide.md), [tests](failover-test-guide.md), optional failover infrastructure | Roles/listeners/lag/loss/recovery/failback/restore: Not demonstrated by this POC run. |
| 20 | Secure identity/network profiles | [Security](security-guide.md), identity/network/application/SQL infrastructure | Actual private access, grants, TLS and evaluation cleanup: Not demonstrated by this POC run. |
| 21 | Public GitHub controls | [Checklist](public-repo-checklist.md), root governance, CI/scanner | Worktree/index/history/evidence checks and owner-configured controls: Not demonstrated by this POC run. |
| 22 | Repository structure | [Documentation index](index.md), root README and directory tree | File inventory and implemented entry points reviewed before release |
| 23 | Customer docs and eight diagrams | [Index](index.md), [diagrams](architecture-diagram.md), root README | Diagrams describe design only; live topology: Not demonstrated by this POC run. |
| 24 | Workshop worksheet | [Workshop](customer-workshop.md) | Customer answers/approval remain TBD, private |
| 25 | Customer implementation prompt | [Implementation prompt](../prompts/customer-poc-implementation-prompt.md) | Prompt reviewed for safety; no execution authorization implied |
| 26 | Analysis prompts | [Results prompt](../prompts/result-analysis-prompt.md), [serverless prompt](../prompts/serverless-analysis-prompt.md) | Grounded report from real sanitized evidence: Not demonstrated by this POC run. |
| 27 | Scaling decisions | [Scaling](scaling-decision-guide.md) | Correlated bottleneck/tuning/capacity evidence: Not demonstrated by this POC run. |
| 28 | Dynamic cost inputs | [Cost](cost-guide.md), collector cost-input artifacts | Exact meter/unit/region/currency/date/usage; savings: Not demonstrated by this POC run. |
| 29 | Evidence and reporting | [Evidence](evidence-guide.md), [templates](results-template.md), Blob persistence/download, sanitizer | Complete raw cloud upload, file/hash verification, provenance, sanitization and manual approval: Not demonstrated by this POC run. |
| 30 | Quality bar | [Contributing](../CONTRIBUTING.md), tests/CI, [publication](public-repo-checklist.md) | Exact local commands/status and blocked prerequisites; cloud validation: Not demonstrated by this POC run. |
| 31 | Final delivery/report | Root README, [executive template](executive-summary-template.md), release summary | Tree, architecture, commands, inputs, limitations and unexecuted checks with verified scope |

Do not change a row to “passed” because the corresponding file exists. Maintain
separate implementation validation and cloud-experiment status. If a collector
or persisted artifacts lack required evidence, state the gap explicitly instead
of populating fabricated observations.
