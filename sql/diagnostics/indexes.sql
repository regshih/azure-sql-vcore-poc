-- Purpose/context: user database row and index storage inventory.
-- Permissions: monitoring VIEW DATABASE STATE and VIEW DEFINITION; newer tiers can require
-- VIEW DATABASE PERFORMANCE STATE plus VIEW SECURITY DEFINITION.
-- Output: schema/table/index names, index ID, row counts, used/reserved MB.
-- Interpret: compare before/after tuning snapshots, accounting for index write/storage costs.
-- Limitations: partition metadata row counts are approximate; no fragmentation scan or rebuild.
SELECT
    s.name AS schema_name, t.name AS table_name, i.name AS index_name, i.index_id,
    SUM(p.row_count) AS approximate_rows,
    SUM(p.used_page_count) / 128.0 AS used_mb,
    SUM(p.reserved_page_count) / 128.0 AS reserved_mb
FROM sys.dm_db_partition_stats AS p
INNER JOIN sys.tables AS t ON p.object_id = t.object_id
INNER JOIN sys.schemas AS s ON t.schema_id = s.schema_id
INNER JOIN sys.indexes AS i ON p.object_id = i.object_id AND p.index_id = i.index_id
WHERE t.is_ms_shipped = 0
GROUP BY s.name, t.name, i.name, i.index_id
ORDER BY used_mb DESC;
