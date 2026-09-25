# Architecture decision records

These records capture accepted **repository design intent**, not production
approval or evidence of a cloud deployment. All POC defaults remain a
**POC assumption, not a confirmed customer requirement.**

| Record | Decision |
| --- | --- |
| [0001](0001-controlled-vcore-comparisons.md) | Same-database controlled A/B/C comparisons; small GP baseline |
| [0002](0002-passwordless-private-default.md) | Passwordless identities and private default with explicit evaluation exception |
| [0003](0003-evidence-before-conclusions.md) | Evidence provenance, missing-data honesty and public sanitization |
| [0004](0004-bounded-resilience-and-cache.md) | Bounded resilience, idempotency and optional consistency-aware caching |
| [0005](0005-availability-is-not-dr.md) | Separate HA, asynchronous single-writer DR and recoverability |

For a material change, add or supersede an ADR describing context, alternatives,
decision, consequences, validation and rollback. Do not silently change a
comparison control or safety boundary. Customer-specific decisions belong in
approved private records, not real values committed here.
