-- Purpose/context: current user database active requests, blocking and locks; no query text.
-- Permissions: monitoring VIEW DATABASE STATE; cross-session visibility is service-tier dependent.
-- Output: request/session IDs, status, elapsed/CPU milliseconds, reads, waits and lock state.
-- Interpret: blocking_session_id > 0 links blockers; a wait is not necessarily an error.
-- Limitations: instantaneous, excludes this session, visibility constrained to permitted sessions.
SELECT
    r.session_id, r.request_id, s.status AS session_status, r.status,
    r.command, r.blocking_session_id, r.wait_type, r.wait_time,
    r.cpu_time, r.total_elapsed_time, r.logical_reads, r.reads, r.writes
FROM sys.dm_exec_requests AS r
INNER JOIN sys.dm_exec_sessions AS s ON r.session_id = s.session_id
WHERE r.database_id = DB_ID() AND r.session_id <> @@SPID
ORDER BY r.total_elapsed_time DESC;

SELECT
    request_session_id, resource_type, request_mode, request_status,
    resource_associated_entity_id
FROM sys.dm_tran_locks
WHERE resource_database_id = DB_ID()
ORDER BY request_session_id, resource_type;
