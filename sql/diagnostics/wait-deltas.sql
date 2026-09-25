-- Purpose/context: user database wait DELTAS across a five-second sample, not lifetime totals.
-- Permissions: monitoring VIEW DATABASE STATE (or supported VIEW DATABASE PERFORMANCE STATE).
-- Output: sample UTC times, wait type, count and wait/signal milliseconds in this interval.
-- Interpret: compare equivalent workload intervals; signal time can indicate scheduler pressure.
-- Limitations: resets/new wait types are flagged/excluded; no DBCC reset; background waits included.
-- Local table variable only; no user data/schema is modified. This sample itself waits five seconds.
DECLARE @StartUtc datetime2 = SYSUTCDATETIME();
DECLARE @Before TABLE (
    wait_type nvarchar(60) PRIMARY KEY,
    waiting_tasks_count bigint,
    wait_time_ms bigint,
    signal_wait_time_ms bigint
);
INSERT INTO @Before
SELECT wait_type, waiting_tasks_count, wait_time_ms, signal_wait_time_ms
FROM sys.dm_db_wait_stats;
WAITFOR DELAY '00:00:05';
DECLARE @EndUtc datetime2 = SYSUTCDATETIME();
SELECT
    @StartUtc AS start_utc, @EndUtc AS end_utc, a.wait_type,
    a.waiting_tasks_count - b.waiting_tasks_count AS waiting_tasks_delta,
    a.wait_time_ms - b.wait_time_ms AS wait_ms_delta,
    a.signal_wait_time_ms - b.signal_wait_time_ms AS signal_wait_ms_delta
FROM sys.dm_db_wait_stats AS a
INNER JOIN @Before AS b ON a.wait_type = b.wait_type
WHERE a.wait_time_ms >= b.wait_time_ms
    AND a.waiting_tasks_count >= b.waiting_tasks_count
    AND a.signal_wait_time_ms >= b.signal_wait_time_ms
    AND a.wait_time_ms > b.wait_time_ms
ORDER BY wait_ms_delta DESC;
SELECT COUNT_BIG(*) AS reset_or_new_wait_types
FROM sys.dm_db_wait_stats AS a
LEFT JOIN @Before AS b ON a.wait_type = b.wait_type
WHERE b.wait_type IS NULL OR a.wait_time_ms < b.wait_time_ms
    OR a.waiting_tasks_count < b.waiting_tasks_count
    OR a.signal_wait_time_ms < b.signal_wait_time_ms;
