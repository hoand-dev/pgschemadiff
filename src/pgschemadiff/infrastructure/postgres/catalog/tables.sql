-- catalog/tables.sql
-- Returns all user-defined tables and partitioned tables from pg_catalog.
-- Excludes system schemas (pg_catalog, information_schema, pg_toast, pg_temp_*).
-- Result columns:
--   schema_name          text      -- owning schema
--   table_name           text      -- table name
--   unlogged             bool      -- true when pg_class.relpersistence = 'u'
--   owner                text      -- role owning the table
--   tablespace           text|null -- non-default tablespace name
--   comment              text|null -- table comment
--   partition_strategy   text|null -- 'h' hash / 'l' list / 'r' range, null if not partitioned
--   partition_expr       text|null -- pg_get_partkeydef(c.oid) or null
--   partition_of_schema  text|null -- parent schema if this table IS a partition
--   partition_of_table   text|null -- parent table name if this table IS a partition
--   partition_bound      text|null -- pg_get_expr(c.relpartbound, c.oid) if this IS a partition
SELECT
    n.nspname                                          AS schema_name,
    c.relname                                          AS table_name,
    c.relpersistence = 'u'                              AS unlogged,
    pg_catalog.pg_get_userbyid(c.relowner)             AS owner,
    table_space.spcname                                AS tablespace,
    pg_catalog.obj_description(c.oid, 'pg_class')      AS comment,
    pt.partstrat::text                                 AS partition_strategy,
    CASE
        WHEN pt.partrelid IS NOT NULL
            THEN pg_get_partkeydef(c.oid)
        ELSE NULL
    END                                                AS partition_expr,
    pn.nspname                                         AS partition_of_schema,
    pc.relname                                         AS partition_of_table,
    CASE
        WHEN c.relispartition
            THEN pg_get_expr(c.relpartbound, c.oid)
        ELSE NULL
    END                                                AS partition_bound
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n
    ON n.oid = c.relnamespace
-- Partition key info (present only for PARTITIONED tables, i.e. relkind='p')
LEFT JOIN pg_catalog.pg_partitioned_table pt
    ON pt.partrelid = c.oid
-- Parent info (present only when this table IS a partition)
LEFT JOIN pg_catalog.pg_inherits inh
    ON inh.inhrelid = c.oid
LEFT JOIN pg_catalog.pg_class pc
    ON pc.oid = inh.inhparent
LEFT JOIN pg_catalog.pg_namespace pn
    ON pn.oid = pc.relnamespace
-- reltablespace = 0 means the database default tablespace (NULL here).
LEFT JOIN pg_catalog.pg_tablespace table_space
    ON table_space.oid = c.reltablespace
WHERE c.relkind IN ('r', 'p')
  AND left(n.nspname, 3) != 'pg_'
  AND n.nspname != 'information_schema'
  AND n.nspname != 'pgschemadiff'
ORDER BY n.nspname, c.relname
