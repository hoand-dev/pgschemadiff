-- catalog/sequence_prerequisites.sql
-- Returns sequence dependencies recorded for column defaults via pg_depend.
-- No default SQL is parsed; dependent -> prerequisite direction is preserved.
-- Result columns: dependent_schema, dependent_table, dependent_column,
--                 sequence_schema, sequence_name
SELECT DISTINCT
    table_namespace.nspname AS dependent_schema,
    table_class.relname AS dependent_table,
    table_attribute.attname AS dependent_column,
    sequence_namespace.nspname AS sequence_schema,
    sequence_class.relname AS sequence_name
FROM pg_catalog.pg_attrdef AS column_default
JOIN pg_catalog.pg_class AS table_class
    ON table_class.oid = column_default.adrelid
JOIN pg_catalog.pg_namespace AS table_namespace
    ON table_namespace.oid = table_class.relnamespace
JOIN pg_catalog.pg_attribute AS table_attribute
    ON table_attribute.attrelid = column_default.adrelid
   AND table_attribute.attnum = column_default.adnum
   AND table_attribute.attnum > 0
   AND NOT table_attribute.attisdropped
JOIN pg_catalog.pg_depend AS sequence_dependency
    ON sequence_dependency.classid = 'pg_catalog.pg_attrdef'::regclass
   AND sequence_dependency.objid = column_default.oid
   AND sequence_dependency.refclassid = 'pg_catalog.pg_class'::regclass
   AND sequence_dependency.deptype = 'n'
JOIN pg_catalog.pg_class AS sequence_class
    ON sequence_class.oid = sequence_dependency.refobjid
   AND sequence_class.relkind = 'S'
JOIN pg_catalog.pg_namespace AS sequence_namespace
    ON sequence_namespace.oid = sequence_class.relnamespace
WHERE table_class.relkind IN ('r', 'p')
   AND left(table_namespace.nspname, 3) != 'pg_'
  AND table_namespace.nspname != 'information_schema'
  AND table_namespace.nspname != 'pgschemadiff'
   AND left(sequence_namespace.nspname, 3) != 'pg_'
  AND sequence_namespace.nspname != 'information_schema'
  AND sequence_namespace.nspname != 'pgschemadiff'
  AND NOT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_depend AS table_extension_dependency
      WHERE table_extension_dependency.classid = 'pg_catalog.pg_class'::regclass
        AND table_extension_dependency.objid = table_class.oid
        AND table_extension_dependency.deptype = 'e'
  )
  AND NOT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_depend AS sequence_extension_dependency
      WHERE sequence_extension_dependency.classid = 'pg_catalog.pg_class'::regclass
        AND sequence_extension_dependency.objid = sequence_class.oid
        AND sequence_extension_dependency.deptype = 'e'
  )
ORDER BY dependent_schema, dependent_table, dependent_column,
         sequence_schema, sequence_name;
