-- catalog/sequences.sql
-- Returns non-extension-owned, non-identity sequences and schema options.
-- Runtime state (last_value/is_called) is deliberately not queried.
-- Result columns:
--   schema_name, sequence_name, data_type, start_value, increment_by,
--   min_value, max_value, cache_size, cycle, owner, owned_schema,
--   owned_table, owned_column
SELECT
    sequence_namespace.nspname AS schema_name,
    sequence_class.relname AS sequence_name,
    format_type(sequence_options.seqtypid, NULL) AS data_type,
    sequence_options.seqstart AS start_value,
    sequence_options.seqincrement AS increment_by,
    sequence_options.seqmin AS min_value,
    sequence_options.seqmax AS max_value,
    sequence_options.seqcache AS cache_size,
    sequence_options.seqcycle AS cycle,
    pg_catalog.pg_get_userbyid(sequence_class.relowner) AS owner,
    owned_namespace.nspname AS owned_schema,
    owned_relation.relname AS owned_table,
    owned_attribute.attname AS owned_column
FROM pg_catalog.pg_class AS sequence_class
JOIN pg_catalog.pg_sequence AS sequence_options
    ON sequence_options.seqrelid = sequence_class.oid
JOIN pg_catalog.pg_namespace AS sequence_namespace
    ON sequence_namespace.oid = sequence_class.relnamespace
LEFT JOIN pg_catalog.pg_depend AS ownership
    ON ownership.classid = 'pg_catalog.pg_class'::regclass
   AND ownership.objid = sequence_class.oid
   AND ownership.refclassid = 'pg_catalog.pg_class'::regclass
   AND ownership.deptype = 'a'
LEFT JOIN pg_catalog.pg_class AS owned_relation
    ON owned_relation.oid = ownership.refobjid
LEFT JOIN pg_catalog.pg_namespace AS owned_namespace
    ON owned_namespace.oid = owned_relation.relnamespace
LEFT JOIN pg_catalog.pg_attribute AS owned_attribute
    ON owned_attribute.attrelid = ownership.refobjid
   AND owned_attribute.attnum = ownership.refobjsubid
   AND owned_attribute.attnum > 0
   AND NOT owned_attribute.attisdropped
WHERE sequence_class.relkind = 'S'
   AND left(sequence_namespace.nspname, 3) != 'pg_'
  AND sequence_namespace.nspname != 'information_schema'
  AND sequence_namespace.nspname != 'pgschemadiff'
  AND NOT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_depend AS identity_dependency
      WHERE identity_dependency.classid = 'pg_catalog.pg_class'::regclass
        AND identity_dependency.objid = sequence_class.oid
        AND identity_dependency.refclassid = 'pg_catalog.pg_class'::regclass
        AND identity_dependency.deptype = 'i'
  )
  AND NOT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_depend AS extension_dependency
      WHERE extension_dependency.classid = 'pg_catalog.pg_class'::regclass
        AND extension_dependency.objid = sequence_class.oid
        AND extension_dependency.deptype = 'e'
  )
ORDER BY sequence_namespace.nspname, sequence_class.relname;
