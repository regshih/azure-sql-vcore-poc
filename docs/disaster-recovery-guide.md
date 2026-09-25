# Optional cross-region disaster recovery

DR is disabled by default. Enabling a secondary region/database adds cost,
networking, identity, operational, and consistency responsibilities. Default
manual failover policy is a **POC assumption, not a confirmed customer
requirement.** Customer **RTO: TBD; RPO: TBD**. Measured DR recovery and loss:
**Not demonstrated by this POC run.**

## Accurate topology

An Azure SQL failover group coordinates primary/secondary roles and offers a
read-write listener and a read-only listener. Normal writes go to **one primary**.
Asynchronous replication copies changes to the secondary; it is not a second
simultaneously writable primary. This write topology is commonly active/passive.

Read-only traffic may use the readable secondary through supported/configured
read-only routing. That does not make writes active/active. Active/active
application tiers can exist in multiple regions but must still respect the
single-writer database topology. Multi-primary write architecture is outside this
POC.

The wired optional module provisions a secondary SQL server/database and a
Manual failover group. It is **SQL-only DR**: the Container Apps application
remains in the primary application region. No cross-region application failover
is provisioned, and a successful SQL role transition cannot prove application
continuity through loss of that region.

The optional infrastructure must be reviewed for a second logical server,
secondary database, regional placement, listener endpoints, failover policy and
supported grace period. Do not enable automatic failover as an undocumented
shortcut. Planned/manual failover and forced data-loss failover have different
risks and approvals.

## Using the secondary for reads

| Consideration | Required design/test |
| --- | --- |
| Replication lag | Measure lag and observed read freshness; async does not guarantee immediate visibility |
| Read-after-write | Route consistency-sensitive reads appropriately; define acceptable staleness TBD |
| Capacity | Read traffic consumes secondary resources; maintain capacity for promoted write workload |
| Cost | Include second database, monitoring, endpoints/network and transfer |
| Routing | Configure explicit read-only access and validate listener behavior; do not assume automatic application read splitting |
| Transaction semantics | Read-only transactions cannot write; code must handle role changes safely |
| Failover | Validate listener resolution, connection pool refresh, retries, and target role before/after |
| Operations | Monitor replication, resource pressure, failed reads, role changes and alert noise |

## Private connectivity and identity

Private endpoints, DNS resolution and routing must work for **both** logical
servers and for the listeners from each application/runner location. A private
endpoint in the primary region does not automatically create a tested recovery
path. Validate listener-to-server resolution before and after failover without
publishing endpoint names or addresses.

Ensure the deployed app identity and contained database grants remain valid
after promotion; verify external identity dependencies and administrative access.
Database replication alone does not recreate app hosting, container images,
configuration, network, DNS, monitoring, or approved operator permissions in the
secondary region. Design and test those independently.

## Test sequence

1. Approve extra costs, intended scope, replication topology and rollback.
2. Capture initial roles, replication state/lag, configuration and marker/write
   validation. Start a low continuous workload through the read-write listener.
3. Validate read-only listener reads separately, recording freshness and role.
4. Execute an approved **planned** failover; record control-plane events and
   client errors/retries/timeouts/recovery.
5. Verify new roles, listener reconnection, idempotent write/readback, freshness
   and stable service. Measure recovery from the customer's client perspective.
6. Perform approved failback, repeat validation, restore original routing.
7. Only if separately authorized, consider forced failover under explicit
   destructive/data-loss gates. Display the data-loss warning before execution.

Follow [failover test details](failover-test-guide.md). A documented product
capability, completed management operation, or local unit test does not establish
RTO/RPO.

## Restore is separate recoverability

Point-in-time restore creates a **new** database to validate retained backups and
recoverable data. It is not a failover or automatic application DR. Record the
selected restore time, operation elapsed time, validation checks, recovered data
boundary, access/network requirements and separate app-switch effort. Do not
overwrite or silently retarget the live POC database. Delete the test copy only
after approved validation and evidence collection.

Backup redundancy/retention are configurable and region dependent. Long-term
retention may prevent serverless auto-pause; do not remove retention requirements
to improve a cost chart. Validate business recovery requirements first.

References: [failover groups](https://learn.microsoft.com/azure/azure-sql/database/failover-group-sql-db),
[active geo-replication](https://learn.microsoft.com/azure/azure-sql/database/active-geo-replication-overview),
[business continuity](https://learn.microsoft.com/azure/azure-sql/database/business-continuity-high-availability-disaster-recover-hadr-overview),
[restore](https://learn.microsoft.com/azure/azure-sql/database/recovery-using-backups).
