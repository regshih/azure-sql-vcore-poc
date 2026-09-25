-- Purpose/context: run independently on the SOURCE at the chosen recovery point and RESTORED DB.
-- Permissions: SELECT on synthetic POC tables and VIEW DEFINITION for constraint visibility.
-- Output: exact counts, seed/migration markers, invalid/orphan/total mismatch counts, constraint flags.
-- Interpret: compare exported source/restored snapshots privately; zero invalid rows is necessary
-- but insufficient to prove PITR correctness. Confirm expected committed marker IDs separately.
-- Limitations: no expected counts invented; writes during scans can make snapshots inconsistent.
-- Quiesce workload or use an approved snapshot-consistent session. Full scans consume resources.
SELECT 'Products' AS table_name, COUNT_BIG(*) AS rows_found FROM dbo.Products
UNION ALL SELECT 'WorkItems', COUNT_BIG(*) FROM dbo.WorkItems
UNION ALL SELECT 'WorkItemLines', COUNT_BIG(*) FROM dbo.WorkItemLines
UNION ALL SELECT 'Activity', COUNT_BIG(*) FROM dbo.Activity
UNION ALL SELECT 'IdempotencyKeys', COUNT_BIG(*) FROM dbo.IdempotencyKeys
UNION ALL SELECT 'DatasetVersions', COUNT_BIG(*) FROM dbo.DatasetVersions
UNION ALL SELECT 'RuntimeConfiguration', COUNT_BIG(*) FROM dbo.RuntimeConfiguration
UNION ALL SELECT 'SchemaMigrations', COUNT_BIG(*) FROM dbo.SchemaMigrations;
SELECT version, generation_seed, product_count, work_item_count, created_at
FROM dbo.DatasetVersions;
SELECT version, checksum, applied_at FROM dbo.SchemaMigrations ORDER BY version;
SELECT [key], value FROM dbo.RuntimeConfiguration;
SELECT
    name AS foreign_key_name, is_disabled, is_not_trusted
FROM sys.foreign_keys
WHERE parent_object_id IN (
    OBJECT_ID('dbo.WorkItemLines'), OBJECT_ID('dbo.Activity'), OBJECT_ID('dbo.IdempotencyKeys')
);
SELECT name AS check_constraint_name, is_disabled, is_not_trusted
FROM sys.check_constraints
WHERE parent_object_id IN (
    OBJECT_ID('dbo.Products'), OBJECT_ID('dbo.WorkItems'), OBJECT_ID('dbo.WorkItemLines')
);
SELECT 'orphan_work_item_line' AS check_name, COUNT_BIG(*) AS violations
FROM dbo.WorkItemLines AS l
LEFT JOIN dbo.WorkItems AS w ON l.work_item_id = w.id
LEFT JOIN dbo.Products AS p ON l.product_id = p.id
WHERE w.id IS NULL OR p.id IS NULL
UNION ALL
SELECT 'orphan_activity', COUNT_BIG(*)
FROM dbo.Activity AS a LEFT JOIN dbo.WorkItems AS w ON a.work_item_id = w.id
WHERE w.id IS NULL
UNION ALL
SELECT 'orphan_idempotency', COUNT_BIG(*)
FROM dbo.IdempotencyKeys AS k LEFT JOIN dbo.WorkItems AS w ON k.work_item_id = w.id
WHERE w.id IS NULL
UNION ALL
SELECT 'invalid_product', COUNT_BIG(*) FROM dbo.Products
WHERE stock_units < 0 OR unit_price_cents < 0
    OR department NOT IN ('operations', 'engineering', 'sales')
UNION ALL
SELECT 'invalid_line', COUNT_BIG(*) FROM dbo.WorkItemLines
WHERE quantity NOT BETWEEN 1 AND 1000 OR unit_price_cents < 0 OR ordinal NOT BETWEEN 0 AND 49
UNION ALL
SELECT 'invalid_work_item', COUNT_BIG(*) FROM dbo.WorkItems
WHERE status NOT IN ('open', 'completed') OR total_cents < 0;
WITH totals AS (
    SELECT work_item_id, SUM(CAST(quantity AS bigint) * unit_price_cents) AS line_total
    FROM dbo.WorkItemLines GROUP BY work_item_id
)
SELECT COUNT_BIG(*) AS work_item_total_mismatches
FROM dbo.WorkItems AS w LEFT JOIN totals AS t ON w.id = t.work_item_id
WHERE t.work_item_id IS NULL OR w.total_cents <> t.line_total;
