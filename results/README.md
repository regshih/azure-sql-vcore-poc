# Evidence boundary

`local-untracked-runs/` contains private, unsanitized run and operator artifacts.
`shareable/` contains generated sanitization output; it remains ignored until a
human reviews it. Neither directory is source code. Do not force-add either.

Missing measurements must remain **Not demonstrated by this POC run.**
An empty series is not zero, a passed mock is not an Azure test, and control-plane
operation completion is not application recovery time.

Use the sanitizer and publication scanner described in the
[public repository checklist](../docs/public-repo-checklist.md).
Retain UTC run IDs, configuration/profile hashes, measured distributions and
redaction reports. Share only the reviewed sanitized bundle, never deployment
outputs, raw query text, customer screenshots, connection strings or local logs.
