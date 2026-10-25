-- catalog/views.sql
-- Returns views and materialized views, output columns, query, physical options, and owner.
-- Schema selection is applied to the assembled rows in Python.
-- Result columns: schema_name, view_name, relation_kind, definition, check_option,
--                 security_barrier, security_invoker, owner, access_method,
--                 tablespace, storage_parameters, is_populated, has_indexes,
--                 column_position, column_name, column_type
SELECT
    view_namespace.nspname AS schema_name,
    view_class.relname AS view_name,
    view_class.relkind AS relation_kind,
    pg_catalog.pg_get_viewdef(view_class.oid, true) AS definition,
    COALESCE(
        (
            SELECT pg_catalog.split_part(option_entry.option_text, '=', 2)
            FROM pg_catalog.unnest(view_class.reloptions) AS option_entry(option_text)
            WHERE pg_catalog.split_part(option_entry.option_text, '=', 1) = 'check_option'
        ),
        'none'
    ) AS check_option,
    COALESCE(
        (
            SELECT pg_catalog.split_part(option_entry.option_text, '=', 2) = 'true'
            FROM pg_catalog.unnest(view_class.reloptions) AS option_entry(option_text)
            WHERE pg_catalog.split_part(option_entry.option_text, '=', 1) = 'security_barrier'
        ),
        false
    ) AS security_barrier,
    COALESCE(
        (
            SELECT pg_catalog.split_part(option_entry.option_text, '=', 2) = 'true'
            FROM pg_catalog.unnest(view_class.reloptions) AS option_entry(option_text)
            WHERE pg_catalog.split_part(option_entry.option_text, '=', 1) = 'security_invoker'
        ),
        false
    ) AS security_invoker,
    pg_catalog.pg_get_userbyid(view_class.relowner) AS owner,
    relation_access_method.amname AS access_method,
    view_tablespace.spcname AS tablespace,
    COALESCE(view_class.reloptions, ARRAY[]::text[]) AS storage_parameters,
    view_class.relispopulated AS is_populated,
    EXISTS (
        SELECT 1
        FROM pg_catalog.pg_index AS materialized_view_index
        WHERE materialized_view_index.indrelid = view_class.oid
    ) AS has_indexes,
    view_attribute.attnum AS column_position,
    view_attribute.attname AS column_name,
    pg_catalog.format_type(view_attribute.atttypid, view_attribute.atttypmod) AS column_type
FROM pg_catalog.pg_class AS view_class
JOIN pg_catalog.pg_namespace AS view_namespace
    ON view_namespace.oid = view_class.relnamespace
LEFT JOIN pg_catalog.pg_am AS relation_access_method
    ON relation_access_method.oid = view_class.relam
LEFT JOIN pg_catalog.pg_tablespace AS view_tablespace
    ON view_tablespace.oid = view_class.reltablespace
JOIN pg_catalog.pg_attribute AS view_attribute
    ON view_attribute.attrelid = view_class.oid
   AND view_attribute.attnum > 0
   AND NOT view_attribute.attisdropped
WHERE view_class.relkind IN ('v', 'm')
  AND left(view_namespace.nspname, 3) != 'pg_'
  AND view_namespace.nspname != 'information_schema'
  AND view_namespace.nspname != 'pgschemadiff'
  AND NOT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_depend AS extension_dependency
      WHERE extension_dependency.classid = 'pg_catalog.pg_class'::regclass
        AND extension_dependency.objid = view_class.oid
        AND extension_dependency.deptype = 'e'
  )
ORDER BY view_namespace.nspname, view_class.relname, view_attribute.attnum;
