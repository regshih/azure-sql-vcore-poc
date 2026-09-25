# ADR 0002: Passwordless private default

**Status:** Accepted for POC design; customer policy TBD.

## Context

A public reusable repository must not embed environment values or credentials.
Simple public connectivity can become an unsafe default.

## Decision

Use Microsoft Entra SQL tokens through DefaultAzureCredential, managed identity
when deployed, TLS certificate validation and Entra-only SQL administration.
Separate bootstrap administrator, runtime contained-user grants, diagnostic and
deployment privileges. Use private SQL endpoint/DNS, SQL public access off and
internal Container Apps/private ingress by default. Registry admin stays off.
No Key Vault is deployed. Azure deployment supplies the protected control token
through encrypted Container Apps secrets, not a default vault.

This passwordless decision covers SQL and supported Redis data access.
Protected experiment controls use a shared bearer secret and actual-peer network
allowlist. The deployment orchestrator generates it cryptographically, passes an
ARM secure parameter through a single-use file with `finally` cleanup, and injects
matching encrypted secret references for app/runner. Redeployment rotates both.
This is not an entirely secretless workflow; the core app does not issue/fetch
the secret. Local operation needs an explicitly supplied token.

Permit an explicitly approved evaluation profile with exact caller IPv4 SQL
firewall and app restriction, never broad ranges or Azure-services bypass.
Customer-specific values remain local/untracked and evidence private until
sanitized.

## Consequences

Private clients/jobs need approved routing and DNS; identity alone is not network
access. Initialization requires a privileged job and verified grants. Production
end-user authentication/authorization is outside this synthetic POC. Enabling
the optional control secret needs a separately reviewed lifecycle and verified
infrastructure wiring. Verify secure-parameter cleanup and keep secret values
out of output, ordinary configuration, repository content and artifacts.

## Validation

Verify observed network rules, token audience/identity, least grants, private DNS
from all callers and cleanup. Live enforcement:
**Not demonstrated by this POC run.**
