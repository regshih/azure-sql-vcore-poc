# Changelog

Document changes here without customer identifiers or fabricated measurements.

## Unreleased

### Fixed

- Supply explicit zero offsets for bounded Azure Blob readback and operator
  downloads; regression coverage exercises the real SDK range validation.
- Map runtime and observer contained SQL users to managed-identity client IDs,
  while retaining object IDs for Azure RBAC and server administration.
- Configure only the documented Container Apps workload-profile platform CIDRs
  for authenticated internal calls; bearer-token and public-network guards remain.
- Consume migration ledger rows explicitly instead of treating SQLAlchemy's
  result object as a dictionary. Regression tests use real cursor results for
  empty, partially applied and fully applied ledgers.

### Added

- Documentation for a General Purpose provisioned baseline, controlled 2-to-4
  comparison, serverless C1/C2 testing, tuning, cache and overload interpretation.
- Architecture diagrams, metrics catalog, schema-aware monitoring examples,
  disabled-alert runbooks, HA/DR/restore guidance and cost-input worksheets.
- Sanitized reporting templates, evidence/publication procedures, design
  decisions, governance and reusable implementation/analysis prompts.

### Evidence status

Live capacity, scaling, serverless pause/resume, failover, restore and cost
savings: **Not demonstrated by this POC run.**

This entry describes repository materials, not a released service, verified
deployment or promised production result. Record actual test/validation status
in release evidence before assigning a release version.
