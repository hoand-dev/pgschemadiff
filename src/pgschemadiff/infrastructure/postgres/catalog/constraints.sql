-- catalog/constraints.sql
-- Returns all constraints (PK, unique, check, FK, exclusion) on user-defined tables.
-- Excludes system schemas (pg_catalog, information_schema, pg_toast, pg_temp_*).
-- Result columns:
--   schema_name        text       -- table's owning schema
--   table_name         text       -- constrained table
--   constraint_name    text       -- pg_constraint.conname
--   constraint_type    text       -- 'p'=PK, 'u'=unique, 'c'=check, 'f'=FK, 'x'=exclusion
--   definition         text       -- pg_get_constraintdef(con.oid, true)
--   ref_schema         text|null  -- referenced schema (FK only, null otherwise)
--   ref_table          text|null  -- referenced table  (FK only, null otherwise)
--   deferrable         bool       -- con.condeferrable
--   initially_deferred bool       -- con.condeferred
SELECT
    n.nspname                                            AS schema_name,
    c.relname                                            AS table_name,
    con.conname                                          AS constraint_name,
    con.contype::text                                    AS constraint_type,
    pg_get_constraintdef(con.oid, true)                  AS definition,
    rn.nspname                                           AS ref_schema,
    rc.relname                                           AS ref_table,
    con.condeferrable                                    AS deferrable,
    con.condeferred                                      AS initially_deferred
FROM pg_catalog.pg_constraint con
JOIN pg_catalog.pg_class c
    ON c.oid = con.conrelid
JOIN pg_catalog.pg_namespace n
    ON n.oid = c.relnamespace
-- Referenced relation (populated only for foreign-key constraints, contype='f')
LEFT JOIN pg_catalog.pg_class rc
    ON rc.oid = con.confrelid
LEFT JOIN pg_catalog.pg_namespace rn
    ON rn.oid = rc.relnamespace
WHERE con.contype IN ('p', 'u', 'c', 'f', 'x')
  AND n.nspname NOT LIKE 'pg_%'
  AND n.nspname != 'information_schema'
ORDER BY n.nspname, c.relname, con.conname
