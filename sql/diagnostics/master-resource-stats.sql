-- Purpose/context: logical server historical resource pressure. Connect separately to master.
-- Permissions: authorized logical-server/master monitoring principal; NOT the runtime user.
-- Output: database_name, UTC interval bounds and CPU/data/log/worker/session percentages.
-- Interpret: compare time-aligned intervals for a single selected database and service objective.
-- Limitations: five-minute aggregates, approximately 14 days retention, not second-scale peaks.
-- Filter database_name locally when a server contains more than this POC database.
SELECT
    database_name, start_time, end_time,
    avg_cpu_percent, avg_data_io_percent, avg_log_write_percent,
    max_worker_percent, max_session_percent
FROM sys.resource_stats
WHERE start_time >= DATEADD(DAY, -1, SYSUTCDATETIME())
ORDER BY database_name, start_time;
