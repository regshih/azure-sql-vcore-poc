## Change summary

Describe the bounded change, why it is needed, and affected ADRs.

## Validation

List exact commands and results. List unavailable tools/unexecuted checks
separately. Do not claim local tests prove cloud behavior.

## Safety and evidence checklist

- [ ] Read SECURITY.md and preserved secure/evaluation profiles.
- [ ] No credentials, tokens, connection strings, real cloud identifiers/names,
  personal information, raw evidence or private paths.
- [ ] Default assumptions use “POC assumption, not a confirmed customer requirement.”
- [ ] Missing results use “Not demonstrated by this POC run.”
- [ ] Customer unknowns remain TBD; measurements and estimates are separate.
- [ ] Provisioned/serverless controls and matrix equivalence preserved or changes explained.
- [ ] Unsafe/destructive flags, warning and explicit approvals remain required.
- [ ] Tests/docs updated and current product claims cite official sources.
- [ ] Sanitizer/scanner checks and manual artifact review completed where applicable.
- [ ] Default CI remains nondeploying.

## Rollback, cost and limitations

Describe restoration/cleanup, paid-resource implications and remaining validation.
