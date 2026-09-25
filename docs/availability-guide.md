# In-region availability

Azure SQL Database includes service-managed high availability; supported zone
redundancy can add protection against a zone failure. Architecture and applicable
service commitments depend on service tier, region, hardware and zone settings.
Do not infer an availability percentage from this repository. Consult the
[current SLA](https://azure.microsoft.com/support/legal/sla/azure-sql-database/)
for the actual configuration.

Customer availability objective: **TBD**. Zone settings are a **POC assumption,
not a confirmed customer requirement.** Observed availability/failover recovery:
**Not demonstrated by this POC run.**

## Availability is not DR

Built-in availability operates within the configured service/region. Cross-region
replication, application recovery, network/DNS, identity, operational readiness,
and recoverable data must be addressed separately. A backup or readable secondary
does not by itself demonstrate application continuity.

General Purpose availability is a managed service architecture, not a user-managed
SQL VM cluster. Do not diagram a fixed number of customer-controllable replicas
or promise zero interruption. Zone redundancy is configurable where supported,
not assumed available for every SKU or serverless combination.

## Client resilience requirements

- Use token-based managed identity, TLS validation, bounded pools and connections
  that can be discarded/re-established after transient failures.
- Retry only classified, safe operations within a shared request deadline,
  maximum attempts, jitter/backoff, retry budget and circuit policy.
- Preserve idempotency for uncertain writes and validate committed state.
- Separate process health from SQL readiness; probe configuration affects
  serverless pause eligibility.
- Use Resource Health for resource-specific incidents, Service Health for broader
  incidents, and Activity Log for control-plane changes. Client observations are
  required to measure actual interruption.

## Planned validation

Run an approved planned in-region availability/failover operation where supported
under low continuous workload. Use [the failover procedure](failover-test-guide.md).
Record operation start/completion, request outcomes/attempts/timeouts, last success,
first success, stable recovery window, and post-recovery integrity checks.
Scale/tier transitions can also validate connection resilience, but they are not
equivalent to every failure or maintenance event.

Do not claim a controlled failover simulates an actual zone outage. Unit fault
injection proves local policy behavior only. Test limitations and unexecuted cloud
steps must remain explicit in the report.

## Operational checklist

| Control | Required evidence |
| --- | --- |
| Supported configuration and zone setting | Captured capabilities and observed settings |
| Health/incident visibility | Correct resource/scope, retained event timestamps, alert route test |
| Connection recovery | Client trace with bounded attempts and stable successful recovery |
| Write safety | No duplicate logical write, idempotency conflict behavior, readback |
| Application tier availability | Separate replica/zone/region design; one-replica POC is not production HA |
| Owner and response runbook | `<availability-owner>` assigned privately; rehearsal and next test date |

References: [local and zone-redundant HA](https://learn.microsoft.com/azure/azure-sql/database/high-availability-sla-local-zone-redundancy),
[Resource Health](https://learn.microsoft.com/azure/service-health/resource-health-overview),
[Service Health](https://learn.microsoft.com/azure/service-health/overview),
[DR guide](disaster-recovery-guide.md).
