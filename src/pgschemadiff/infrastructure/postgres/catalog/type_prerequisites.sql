-- catalog/type_prerequisites.sql
-- Returns enum types referenced by user table columns, including enum arrays.
-- Extension-owned types and system/reserved schemas are excluded.
-- Result columns:
--   table_schema text -- schema owning the dependent table
--   table_name   text -- table containing the column
--   type_schema  text -- schema owning the required enum type
--   type_name    text -- required enum type name
SELECT DISTINCT
    table_namespace.nspname AS table_schema,
    table_class.relname AS table_name,
    n.nspname AS type_schema,
    enum_type.typname AS type_name
FROM pg_catalog.pg_attribute AS a
JOIN pg_catalog.pg_class AS table_class
    ON table_class.oid = a.attrelid
JOIN pg_catalog.pg_namespace AS table_namespace
    ON table_namespace.oid = table_class.relnamespace
JOIN pg_catalog.pg_type AS column_type
    ON column_type.oid = a.atttypid
JOIN pg_catalog.pg_type AS enum_type
    ON enum_type.oid = CASE
        WHEN column_type.typelem <> 0 THEN column_type.typelem
        ELSE column_type.oid
    END
JOIN pg_catalog.pg_namespace AS n
    ON n.oid = enum_type.typnamespace
JOIN pg_catalog.pg_enum AS enum_label
    ON enum_label.enumtypid = enum_type.oid
WHERE table_class.relkind IN ('r', 'p')
  AND a.attnum > 0
  AND NOT a.attisdropped
  AND table_namespace.nspname NOT LIKE 'pg_%'
  AND table_namespace.nspname != 'information_schema'
  AND table_namespace.nspname != 'pgschemadiff'
  AND n.nspname NOT LIKE 'pg_%'
  AND n.nspname != 'information_schema'
  AND n.nspname != 'pgschemadiff'
  AND NOT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_depend AS d
      WHERE d.classid = 'pg_catalog.pg_type'::regclass
        AND d.objid = enum_type.oid
        AND d.deptype = 'e'
  )
ORDER BY table_namespace.nspname, table_class.relname,
         n.nspname, enum_type.typname;
