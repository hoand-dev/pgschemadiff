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
--   partitioned       bool       -- index relation has relkind 'I'
--   attached_to_parent bool      -- child index is attached to a parent index
--   index_definition  text       -- full CREATE [UNIQUE] INDEX … statement
--   include_columns   text[]      -- names after the first indnkeyatts index attributes
--   constraint_name   text|null   -- owning PK/UNIQUE/EXCLUSION constraint, if any
--   predicate         text|null  -- WHERE clause expression or null (non-partial indexes)
SELECT
    n.nspname                                            AS schema_name,
    c.relname                                            AS table_name,
    ic.relname                                           AS index_name,
    am.amname                                            AS index_method,
    i.indisunique                                        AS is_unique,
    i.indisprimary                                       AS is_primary,
    i.indisexclusion                                     AS is_exclusion,
    ic.relkind = 'I'                                     AS partitioned,
    EXISTS (SELECT 1 FROM pg_catalog.pg_inherits WHERE inhrelid = i.indexrelid)
                                                         AS attached_to_parent,
    pg_get_indexdef(i.indexrelid)                        AS index_definition,
    ARRAY(
        SELECT a.attname::text
        FROM generate_series(i.indnkeyatts, i.indnatts - 1) AS k(position)
        JOIN pg_catalog.pg_attribute a
            ON a.attrelid = i.indrelid
           AND a.attnum = i.indkey[k.position]
        ORDER BY k.position
    )                                                    AS include_columns,
    con.conname                                          AS constraint_name,
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
LEFT JOIN pg_catalog.pg_constraint con
    ON con.conindid = i.indexrelid
   AND con.contype IN ('p', 'u', 'x')
WHERE n.nspname NOT LIKE 'pg_%'
  AND n.nspname != 'information_schema'
  AND n.nspname != 'pgschemadiff'
ORDER BY n.nspname, c.relname, ic.relname
