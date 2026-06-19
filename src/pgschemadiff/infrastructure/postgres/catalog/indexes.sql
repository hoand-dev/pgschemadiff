-- catalog/indexes.sql
-- Returns all indexes on user-defined tables (including primary-key indexes).
-- Excludes system schemas (pg_catalog, information_schema, pg_toast, pg_temp_*).
-- Result columns:
--   schema_name       text       -- table's owning schema
--   table_name        text       -- indexed table name
--   index_name        text       -- pg_class.relname for the index object
--   index_method      text       -- pg_am.amname (btree, hash, gist, gin, brin, spgist, …)
--   is_unique         bool       -- pg_index.indisunique
--   is_primary        bool       -- pg_index.indisprimary
--   is_exclusion      bool       -- pg_index.indisexclusion
--   index_definition  text       -- full CREATE [UNIQUE] INDEX … statement
--   predicate         text|null  -- WHERE clause expression or null (non-partial indexes)
SELECT
    n.nspname                                            AS schema_name,
    c.relname                                            AS table_name,
    ic.relname                                           AS index_name,
    am.amname                                            AS index_method,
    i.indisunique                                        AS is_unique,
    i.indisprimary                                       AS is_primary,
    i.indisexclusion                                     AS is_exclusion,
    pg_get_indexdef(i.indexrelid)                        AS index_definition,
    CASE
        WHEN i.indpred IS NOT NULL
            THEN pg_get_expr(i.indpred, i.indrelid)
        ELSE NULL
    END                                                  AS predicate
FROM pg_catalog.pg_index i
JOIN pg_catalog.pg_class c
    ON c.oid = i.indrelid
JOIN pg_catalog.pg_class ic
    ON ic.oid = i.indexrelid
JOIN pg_catalog.pg_namespace n
    ON n.oid = c.relnamespace
JOIN pg_catalog.pg_am am
    ON am.oid = ic.relam
WHERE n.nspname NOT LIKE 'pg_%'
  AND n.nspname != 'information_schema'
ORDER BY n.nspname, c.relname, ic.relname
