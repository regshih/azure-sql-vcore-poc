# Contributing

Contribute small, reviewable changes using synthetic data and placeholder-only
configuration. Read [README](README.md), [SECURITY](SECURITY.md),
[architecture](docs/architecture.md), [assumptions](docs/assumptions.md),
[ADRs](docs/adr/README.md), and [conduct](CODE_OF_CONDUCT.md) first.
Inspect Git status and preserve unrelated work.

## Change discipline

1. Explain the problem, scope, safety effects and expected validation.
2. Preserve secure/evaluation profiles, managed identity, bounded resilience and
   equivalent provisioned/serverless experiments.
3. Add focused tests for behavior changes and update directly related docs.
4. Mark every new default **POC assumption, not a confirmed customer requirement.**
   Leave unknown customer objectives **TBD**.
5. Never invent benchmark, saturation, pause, availability, DR or cost results.
   Missing evidence is **Not demonstrated by this POC run.**
6. Never commit local customer config, identifiers, passwords, connection strings,
   tokens, raw results or personal information.
7. Cite current official product documentation for service-behavior changes;
   explain changed requirements or comparison controls in an ADR.

## Local validation

Use Python 3.12 and the [local environment setup](docs/deployment-guide.md#prerequisites-and-local-configuration).
The remote SQL bootstrap operation is not a dependency installer. From an
already prepared environment, the common checks are:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pytest -m "not azure and not sql"
.\.venv\Scripts\python.exe -m build
.\.venv\Scripts\python.exe -m bandit -r src
.\.venv\Scripts\python.exe -m pip_audit
.\.venv\Scripts\python.exe -m src.experiments.scan --root .
```

Use the current CI configuration/manifest as the authoritative command set if it
changes. Run focused tests while developing, then required checks before review.
Compile/lint Bicep with the installed Bicep CLI, validate migration ordering and
T-SQL with configured tooling, and syntax-check both PowerShell and Bash wrappers
where their tools are available. Building an artifact is not a deployment.

Run configured gitleaks, independent secret scanning and pre-commit hooks; include
worktree, staged content, history and evidence scope. If any tool is unavailable,
record the exact unexecuted command and prerequisite, not a passed status.
Live SQL/Azure tests must be explicitly approved and use disposable configured
targets; they are not part of ordinary public CI.

The consolidated predeployment validator is
`python -m src.operations.validate`. Its default mode is strict. Explicit
`--skip-bicep`, `--skip-security`, `--skip-shell`, or `--allow-missing-tools`
options produce a **partial validation record**, not equivalent evidence to a
complete strict run. Do not use skips merely to make a failed check appear passed.
Missing/skip status and the exact strict command still required must be reported.

Use repeated `--only` selections for focused checks: `python`, `tests`, `imports`,
`sql`, `bicep`, `shell`, or `security`. A selected subset is not complete release
validation. Default test children disable inherited live-test flags. The explicit
`--include-cloud` option additionally requires `RUN_AZURE_SQL_TESTS=1`, valid
approved credentials and disposable targets; it is not permission to run against
an arbitrary database. Default validation does not intentionally execute cloud
tests, although package/advisory tools may require internet access.

Shell validation can be syntax-only. In particular, PowerShell AST parsing is
not proof that wrappers executed under the host's execution policy. Never
bypass that policy to turn a validation result green. Module `--help` validation
must exit without starting services or executing placeholder commands.
Prefer direct Python module entry points when organizational policy blocks
PowerShell script execution; do not change that policy for this POC.

Dashboard and diagnostic source contracts are documented in
[dashboards](dashboards/README.md), [SQL diagnostics](sql/diagnostics/README.md),
[Query Store](sql/query-store/README.md), and
[restore validation](sql/restore-validation/README.md).

## Pull request checklist

Describe behavior changes, tests, docs, assumptions, comparison effects,
rollback/cleanup and remaining limitations. Attach only approved sanitized
evidence. Do not change measured results without provenance or silently rewrite
history. Do not add cloud deployment to default CI.

Owners separately configure rulesets, required reviews/checks, protected
environments, OIDC and alert routes. No contribution should claim these were
enabled merely by adding files.

Contributions are accepted under [MIT](LICENSE). Submit only content you may
license, and preserve applicable third-party notices. No contributor agreement
or company endorsement is implied by this repository.
