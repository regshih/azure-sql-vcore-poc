# Restore integrity and recovery-point validation

Run [integrity.sql](integrity.sql) on the source at a recorded UTC point, then run it on the
separately restored database. Never replace or overwrite the source to perform validation.
The script only reads synthetic tables and catalog metadata. Its exact counts and total
checks scan tables: schedule them deliberately and stop writes or establish an approved
consistent snapshot. Runtime permissions may not include these direct reads.

Compare the actual captured dataset marker, eight table counts, foreign-key/check-constraint
enabled/trusted state, orphan checks, stock/price/status checks, and work-item line totals.
Compare the migration ledger's version/checksum rows to the source and the repository's ordered
migrations (SHA-256 over UTF-8 content normalized to LF); do not assume a fabricated latest
version. Compare the captured runtime tuning configuration as well. Seed-manifest work-item
counts are lower bounds once application writes have occurred, not exact live expectations.
Record any absent tables
or inaccessible catalogs as a failed/incomplete validation, not a pass. A source snapshot
taken after the restore point can legitimately differ; exact equality alone is not an RPO test.

For a recovery-point experiment, create a synthetic work item through the authenticated API,
save its returned ID, idempotency key and committed UTC time **privately**, and record whether
the selected recovery timestamp should contain that marker. Check the marker with the API on
the restored target. Do not invent expected marker IDs or row counts. Also perform the
application smoke/transaction test against the restored target before claiming recovery.
These read-only scripts do not provision a restore or manufacture success evidence.

Reference: [Recover an Azure SQL database using backups](https://learn.microsoft.com/azure/azure-sql/database/recovery-using-backups).
