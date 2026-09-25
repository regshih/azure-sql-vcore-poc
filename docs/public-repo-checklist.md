# Public repository and evidence release checklist

Run this checklist before first publication and after material changes. A clean
ignore file alone is not sufficient: ignored content may already be tracked,
staged, in history, in an artifact, or visible in logs.
Publication approval and complete history review:
**Not demonstrated by this POC run.**

## Source and history

- [ ] Worktree, index/staged contents, every reachable Git revision and generated
  evidence have been scanned within the intended repository scope.
- [ ] No populated `.env`, local settings, CLI caches, state, database backup,
  certificate/key, credential file, virtual environment or deployment output.
- [ ] No passwords, tokens, connection strings or authentication headers.
- [ ] No real customer/company names, personal information, local profile paths,
  usernames, server/database/resource-group names, IPs, or cloud identifiers.
- [ ] Example values are named placeholders/environment variables, not plausible
  fake identifiers that could be mistaken for live configuration.
- [ ] No copied private/internal documentation, unsupported endorsement or
  unlicensed third-party content; dependencies/assets reviewed.
- [ ] Tests, docs, prompts, issue templates and command examples also scanned.
- [ ] All intentional scanner allowances are narrowly scoped, justified and
  reviewed; no broad exclusions for source/docs or unknown secret patterns.

## Scanners and repository settings

```powershell
.\.venv\Scripts\python.exe -m src.experiments.scan --root .
.\.venv\Scripts\python.exe -m src.experiments.scan --root . --redactions <local-redaction-list-path>
```

These are alternative full-repository scans; add the second option when approved
private customer-specific redaction terms are available. The direct entry point is
`python -m src.experiments.scan`. Default scope includes worktree, staged content,
Git history and ignored evidence. `--no-git` is only for scanning a separate
evidence-only directory; it is **not** a full publication check.

Also run configured **gitleaks** and an independent scanner such as **TruffleHog**
when available. Inspect current versions' help before invocation; report an
unavailable scanner as not executed, not passed. Run the configured pre-commit
hooks before staging; CI scanning is a second layer, not the first.

Inspect both `passed` and tool-status fields in the scanner's JSON. Custom checks
can find no issues while `gitleaks` reports it was not installed; that does not mean
gitleaks ran successfully. Preserve the scope and unavailable-tool status in the
private validation record.

Record how many commits were actually scanned. A successful scanner invocation
against zero commits does not provide historical assurance. Keep findings from
ignored private configuration and raw evidence visible; do not broadly allow
source assignments or suppress the evidence tree to obtain a passing result.
For publication, prepare a separate clean checkout containing only reviewed
source and sanitized artifacts, preserving the original private workspace and
evidence. Scan that exact publication checkout and its actual history again.

Repository owners must explicitly configure:

- GitHub secret scanning and push protection where available, plus remediation
  contacts and a reviewed exception process.
- Dependabot alerts/security updates and dependency review as appropriate.
- Required checks, PR review and protected branch/ruleset policy.
- CodeQL where supported and applicable.
- Restricted workflow permissions and controlled third-party actions.
- A protected deployment environment with reviewers and OIDC federation if cloud
  deployment is later enabled. Nondeploying CI remains the default.

  The deployment workflow additionally checks for an existing protected `poc`
  environment with required reviewers. Owners configure the named `AZURE_*`
  identity inputs and `POC_REGION`, `POC_RESOURCE_GROUP`, and
  `POC_ENVIRONMENT_NAME` privately according to the workflow contract. Required
  reviewers, federation and effective restrictions must be verified in repository
  settings; their presence in workflow source is not proof they were configured.

These settings are recommendations requiring owner action; repository files do
not prove they are enabled.

## Evidence and screenshots

- [ ] Real runs remain in ignored `results\local-untracked-runs` or equivalent
  private approved storage, including the private cloud Blob evidence container.
- [ ] Cloud-run full artifact upload succeeded; downloaded file inventory and
  SHA-256 hashes match the persistence receipt. Console summaries are not
  accepted as a substitute for missing raw artifacts.
- [ ] Sanitizer produced a separate shareable bundle without overwriting raw
  evidence, plus a sanitization report.
- [ ] Allowlisted numeric metrics retain meaning/units/timestamps; sensitive
  values in keys, nested objects, strings, filenames and paths are reviewed.
- [ ] Identifiers, customer terms, endpoints, IPs, SQL text/parameters, tokens,
  usernames and private local paths removed or replaced.
- [ ] No raw cloud response, Activity Log claims/caller data, screenshots,
  deployment output or console archive included.
- [ ] Missing measurements remain exactly **Not demonstrated by this POC run.**
- [ ] Measured results, estimates, documentation, general guidance,
  recommendations and unknowns are separate.
- [ ] A human reviewed the final extracted bundle, not only the scanner summary.
- [ ] Scan the resulting bundle and source again after the last content change.

See [evidence procedure](evidence-guide.md). For a leak, stop release, revoke or
rotate exposed credentials immediately through approved processes, restrict
artifacts, notify maintainers privately, and assess history remediation.
Deleting the current file does not revoke a credential or erase history/forks.

## Final release record

Record version/commit, validation commands and statuses, missing tools, reviewed
bundle hash, license review, approving owner and release date privately. Public
notes may summarize verified checks without identifiers or personal information.
Do not state “no secrets anywhere” based on one scanner; say what scope and tools
were checked and retain residual limitations.
