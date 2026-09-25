-- Purpose/context: recent database connection failures/events. Connect separately to master.
-- Permissions: authorized master monitoring principal; not the runtime application's identity.
-- Output: database/UTC interval, successful/failed/terminated/throttled connections and event type.
-- Interpret: correlate event counts to application attempts and platform state, not API finals.
-- Limitations: aggregates/delayed logging, retained up to ~30 days subject to service limits;
-- visibility varies. Query text, usernames, IP addresses and free-form descriptions omitted.
SELECT
    database_name, start_time, end_time, success_count,
    total_failure_count, connection_failure_count,
    terminated_connection_count, throttled_connection_count
FROM sys.database_connection_stats
WHERE start_time >= DATEADD(HOUR, -1, SYSUTCDATETIME())
ORDER BY start_time;
SELECT
    database_name, start_time, end_time, event_category,
    event_type, event_subtype_desc, severity, event_count
FROM sys.event_log
WHERE start_time >= DATEADD(HOUR, -1, SYSUTCDATETIME())
ORDER BY start_time;
