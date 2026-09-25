-- Purpose/context: user database files, allocated/used MB and current service objective.
-- Permissions: metadata visibility; FILEPROPERTY/DMV results may require monitoring privileges.
-- Output: UTC sample, file type and allocated/used MB, objective, automatic tuning state.
-- Interpret: retain timestamped snapshots privately to calculate storage growth.
-- Limitations: FILEPROPERTY SpaceUsed can be NULL; data allocation is not billable compute.
SELECT
    SYSUTCDATETIME() AS sampled_utc, file_id, type_desc,
    size / 128.0 AS allocated_mb,
    FILEPROPERTY(name, 'SpaceUsed') / 128.0 AS used_mb,
    max_size, growth, is_percent_growth
FROM sys.database_files;
SELECT database_id, edition, service_objective, elastic_pool_name
FROM sys.database_service_objectives
WHERE database_id = DB_ID();
SELECT name, desired_state_desc, actual_state_desc, reason_desc
FROM sys.database_automatic_tuning_options;
