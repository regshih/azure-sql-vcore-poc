-- Purpose/context: explicitly opt in to inspecting one Query Store query's raw SQL text.
-- Permissions: monitoring VIEW DATABASE STATE (or supported VIEW DATABASE PERFORMANCE STATE).
-- Output: query ID and raw query text ONLY when the local opt-in flag is changed to 1.
-- Interpret: use a measured query ID from top-queries.sql; inspect parameters/shape privately.
-- Limitations: text can contain confidential literals. Never publish this result, never execute it.
-- Retention follows Query Store configuration. Defaults return NO ROWS; no plan forcing/reset.
DECLARE @IncludeQueryText bit = 0;
DECLARE @QueryId bigint = NULL;
SELECT q.query_id, t.query_sql_text
FROM sys.query_store_query AS q
INNER JOIN sys.query_store_query_text AS t ON q.query_text_id = t.query_text_id
WHERE @IncludeQueryText = 1 AND q.query_id = @QueryId;
