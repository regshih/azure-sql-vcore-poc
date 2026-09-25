-- Purpose/context: current user database resource pressure; run as a monitoring identity.
-- Permissions: VIEW DATABASE STATE (or supported VIEW DATABASE PERFORMANCE STATE).
-- Output: UTC end_time, CPU/data/log percentages, maximum workers/sessions, CPU limit.
-- Interpret: repeated near-limit samples indicate pressure, not a proof of its cause.
-- Limitations: ~15-second samples retained ~1 hour; percentages use this database's limits.
SELECT
    end_time, avg_cpu_percent, avg_data_io_percent, avg_log_write_percent,
    max_worker_percent, max_session_percent, cpu_limit
FROM sys.dm_db_resource_stats
WHERE end_time >= DATEADD(HOUR, -1, SYSUTCDATETIME())
ORDER BY end_time;
