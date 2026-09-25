# Failover and restore test runbook

Customer RTO/RPO and acceptable interruption are **TBD**. Test frequency,
traffic rate, stability window and stop limits are a **POC assumption, not a
confirmed customer requirement.** Recovery behavior:
**Not demonstrated by this POC run.**

## Mandatory gates

- Confirm a disposable POC database, exact local scope, ownership, budget,
  privileges, current roles/configuration and approved maintenance window.
- Explicitly approve each scale, tier switch, planned failover, failback, restore
  and destruction operation. Prior approval to build the repository is not
  approval to execute these operations.
- Forced failover additionally requires `--allow-destructive-tests` and
  `--allow-data-loss`, as well as `--confirm-poc`, and a displayed data-loss
  warning. Do not remove gates to make automation convenient.
- Keep config/outputs private. Do not substitute arbitrary production targets.
- Prepare a safe rollback/failback path, validate network/DNS in both regions
  where relevant, and stop if the observed scope differs from intent.

## Continuous client evidence

Run low continuous traffic with a stable test-run ID and correlation IDs.
Capture UTC for last successful operation before interruption, all errors and
retry attempts, first successful operation after interruption, and return to a
predeclared sustained-success/latency window. Record actual database role where
known, read-write listener behavior, read-only route behavior and write readback.

The **control-plane operation duration**, **first-success recovery**, and
**stable client recovery** are distinct measures. Define their start/stop events
before testing. RPO needs committed-marker/data-loss checks, not just elapsed
operation time. A zero-loss planned test does not establish zero RPO for a forced
regional outage.

The matrix's `failover-application.json` can record a sampled
five-consecutive-success recovery criterion. This is a **POC assumption, not a
confirmed customer requirement.** Record sampling interval, operation coverage
and latency boundaries; five successes do not demonstrate customer RTO, RPO
or sustained recovery under production demand.

```powershell
.\.venv\Scripts\python.exe -m src.experiments.runner --profile failover --host <base-url> --product-count <observed-product-count> --observe-dataset-state
```

Run the workload in a separate process/terminal from the approved control-plane
operation and ensure both use the same UTC window. The load command itself does
not authorize or execute failover.

## Planned in-region operation

```powershell
.\.venv\Scripts\python.exe -m src.operations.cli failover-test --config <local-config-path> --confirm-poc
```

Inspect the wrapper/module help and supported SKU operation before execution.
A supported planned failover is a connection-resilience test, not proof of a
real zone outage or all maintenance scenarios. Verify return to the intended
configuration and compare [availability](availability-guide.md).

The wrapper uses the operations module's authenticated management-plane REST
`POST` to the database `failover` operation with API version `2023-08-01`,
including bounded asynchronous-operation polling. It does not assume an
`az sql db failover` command exists. Matrix automation must invoke the shared
operations command rather than constructing an unsupported CLI command or
bypassing its scope/approval checks. Management-operation completion still
requires separate client-recovery and data-integrity evidence.
An unsupported General Purpose failover operation must remain an explicit
failure, not a synthetic passing result. Successful capability or price queries
do not prove that failover is supported or that client recovery occurred.

## Optional planned geo-failover and failback

Only after the optional failover group and both-region prerequisites are
explicitly enabled and verified:

```powershell
.\.venv\Scripts\python.exe -m src.operations.cli failover-test --config <local-config-path> --confirm-poc --geo
```

Check replication state/lag before the planned transition; log requested/observed
roles and operation outcome. Validate listener reconnect, writes, idempotency and
read-only consistency after transition. Failback requires its own approval and
the same validation. Do not assume the local config automatically changed to
match the promoted primary.

```powershell
.\.venv\Scripts\python.exe -m src.operations.cli failover-test --config <local-config-path> --confirm-poc --geo --failback
```

## Optional forced geo-failover

**Warning: forced failover can lose committed data that has not reached the
secondary.** The POC must not silently force a transition when planned failover
fails. Separate destructive authorization is required immediately before use.

```powershell
.\.venv\Scripts\python.exe -m src.operations.cli failover-test --config <local-config-path> --confirm-poc --geo --allow-destructive-tests --allow-data-loss
```

Verify the command's current help maps those flags to the intended forced path.
Capture last acknowledged write markers and recovered state, loss/uncertainty,
replication limitations, and recovery behavior. Stop instead of widening scope
or skipping gates if prerequisites are incomplete.

## Point-in-time restore

```powershell
.\.venv\Scripts\python.exe -m src.operations.cli restore-test --config <local-config-path> --confirm-poc --restore-time <restore-point-utc>
```

Choose a restore point within the observed retained window, using an explicit UTC
ISO-8601 timestamp. The operation generates a **new** destination and records its
name privately; do not overwrite or retarget the original app automatically.
Validate schema version, row counts, referential integrity, known committed
markers and expected time boundary using safe restore-validation scripts.
Document the separate steps required to point an application at the restored
copy. Restore success is recoverability evidence, not failover-group DR evidence.

## Test record

| Required field | Current value |
| --- | --- |
| Customer RTO/RPO and stability criteria | TBD |
| Approved scope, operation, UTC, operator role | Private record only |
| Original/current roles and listener routes | Not demonstrated by this POC run. |
| Replication state/lag before and after | Not demonstrated by this POC run. |
| Management-operation elapsed time | Not demonstrated by this POC run. |
| Errors/retries/timeouts and first-success recovery | Not demonstrated by this POC run. |
| Stable client recovery and tail latency | Not demonstrated by this POC run. |
| Duplicate-write and consistency validation | Not demonstrated by this POC run. |
| Lost/unconfirmed writes and limitations | Not demonstrated by this POC run. |
| Failback/restoration/cleanup verification | Not demonstrated by this POC run. |

Reference: [failover-group management](https://learn.microsoft.com/azure/azure-sql/database/failover-group-sql-db),
[restore from backups](https://learn.microsoft.com/azure/azure-sql/database/recovery-using-backups).
