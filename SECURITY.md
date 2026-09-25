# Security policy

This is a synthetic-data POC, not a production security certification, supported
Azure product, or endorsement by any company. Maintainers review reports on a
best-effort basis; there is no guaranteed response time or supported-version SLA.

## Report privately

Do not put secrets, real resource identifiers, customer information, personal
data, exploitable details, raw logs or live endpoints in public issues or pull
requests. Use GitHub private vulnerability reporting when enabled. If unavailable,
open only a neutral request for a private reporting route with no sensitive
details. Repository owners must establish and publish an approved private route
before broad adoption.

A useful private report includes affected revision/component, sanitized
reproduction, expected/actual behavior, impact, prerequisites and proposed fix.
Test only in a disposable environment you are authorized to use. Do not probe
other deployments, disrupt services or publish a proof of exploitation.

## Exposed credentials or data

Stop sharing the artifact. Revoke/rotate credentials through approved channels,
restrict artifact access, notify the responsible owner privately, and assess
history/artifact/fork exposure. Deleting the current file is not revocation.
Coordinate any history cleanup; do not silently rewrite shared history.

## Baseline controls and limitations

- Entra tokens and separate managed identities; no SQL password.
- Private SQL and app network defaults; explicit exact-IP evaluation opt-in.
- Least-privilege runtime SQL permissions; separate bootstrap/diagnostic roles.
- Unsafe workloads and destructive operations require explicit gates.
- Nondeploying CI; cloud operations require approved scope and protected OIDC
  setup if a workflow is enabled.
- Raw results/private configuration excluded from Git; scan and sanitize before
  release.
- Full cloud-run artifacts persist to private Blob Storage through managed
  identity; persistence failures fail the job. Download with separately approved
  read permissions and private connectivity, verify hashes, then sanitize.

See [security guide](docs/security-guide.md), [threat model](threat-model.md), and
[public release checklist](docs/public-repo-checklist.md). Local tests do not
prove live control effectiveness: **Not demonstrated by this POC run.**
