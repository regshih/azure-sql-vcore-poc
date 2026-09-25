# ADR 0005: Separate availability, DR and restore

**Status:** Accepted for POC design; customer RTO/RPO/availability TBD.

## Decision

Document built-in SQL availability and supported optional zone redundancy without
inventing an SLA. Keep cross-region failover groups optional, manual by default,
and explicit about asynchronous replication and one writable primary. A readable
secondary or active/active app tier does not create multi-primary SQL writes.

Require approved planned failover/failback tests with continuous client evidence,
role/listener validation and data integrity checks. Forced promotion requires
separate destructive/data-loss gates and warning. Point-in-time restore is a
separate new-database recoverability test.

## Consequences

Application/network/DNS/identity recovery must be designed for both regions.
Optional replicas cost money, may lag and need capacity. Geo-replication/failover
groups and some retention/DNS features prevent serverless pause; do not sacrifice
required recovery behavior to improve a cost estimate.

## Validation

Measure management duration, first-success and stable client recovery separately;
validate lost/unconfirmed writes and failback. A local policy test or documented
service feature establishes neither RTO nor RPO.
Measured HA/DR/restore: **Not demonstrated by this POC run.**
