-- Purpose/context: user database missing-index ESTIMATES for investigation only.
-- Permissions: monitoring VIEW DATABASE STATE; supported-tier visibility restrictions apply.
-- Output: object ID, seek/scan counts, estimated cost/impact and candidate column lists.
-- Interpret: review existing indexes and prove improvements using equivalent measured workloads.
-- Limitations: volatile/resettable estimates, no DDL generation, no automatic recommendation.
-- Column metadata can be sensitive: keep unredacted results private.
SELECT TOP (20)
    d.object_id, gs.user_seeks, gs.user_scans,
    gs.avg_total_user_cost, gs.avg_user_impact,
    d.equality_columns, d.inequality_columns, d.included_columns
FROM sys.dm_db_missing_index_details AS d
INNER JOIN sys.dm_db_missing_index_groups AS g ON d.index_handle = g.index_handle
INNER JOIN sys.dm_db_missing_index_group_stats AS gs
    ON g.index_group_handle = gs.group_handle
WHERE d.database_id = DB_ID()
ORDER BY gs.avg_user_impact DESC;
