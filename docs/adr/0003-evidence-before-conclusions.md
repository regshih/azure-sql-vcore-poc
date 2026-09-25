# ADR 0003: Evidence before conclusions

**Status:** Accepted for documentation, testing and publication.

## Decision

Each run records UTC, configuration, versions, hashes, changed variable, workload
acceleration and coverage. Separate measured results, estimates, product
documentation, general guidance, recommendations and unknowns. Unknown customer
objectives are TBD. Every default is a **POC assumption, not a confirmed customer
requirement.** Every missing result is **Not demonstrated by this POC run.**

Keep raw runs and deployment outputs private/ignored. Cloud runner jobs persist
all raw files to private Blob Storage through managed identity and scoped data
permissions; configured persistence failures must fail the job. Local runs can
persist directly to ignored directories. `POC_EVIDENCE` logs contain inventory,
SHA-256 hashes and run-prefix receipts, not raw file contents. Authorized
VNet-connected downloads verify completeness before structured sanitization,
independent scanning and manual review produce a shareable bundle.

## Rationale and consequences

Synthetic data does not remove sensitive environment metadata. Regex cannot
recognize every customer term. Allowlisted summaries reduce leakage but may omit
diagnostic detail; preserve private originals and document transformations.
Local tests validate implementation paths, not live Azure behavior.

CPU% is not billing, no requests is not paused, operation completion is not stable
client recovery, and a timeout is not automatically throttling. Evidence may
legitimately lead to “more testing required.”

## Validation

Test sanitizer/collector behavior, inspect scope/coverage and follow
[publication checks](../public-repo-checklist.md). Cloud conclusions remain
unproven until actual reviewed runs exist.
