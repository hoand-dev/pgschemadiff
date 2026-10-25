-- catalog/views.sql
-- Returns ordinary views, output columns in ordinal order, options, query, and owner.
-- Schema selection is applied to the assembled rows in Python.
-- Result columns: schema_name, view_name, definition, check_option,
--                 security_barrier, security_invoker, owner,
--                 column_position, column_name, column_type
SELECT
    view_namespace.nspname AS schema_name,
    view_class.relname AS view_name,
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
    view_attribute.attnum AS column_position,
    view_attribute.attname AS column_name,
    pg_catalog.format_type(view_attribute.atttypid, view_attribute.atttypmod) AS column_type
FROM pg_catalog.pg_class AS view_class
JOIN pg_catalog.pg_namespace AS view_namespace
    ON view_namespace.oid = view_class.relnamespace
JOIN pg_catalog.pg_attribute AS view_attribute
    ON view_attribute.attrelid = view_class.oid
   AND view_attribute.attnum > 0
   AND NOT view_attribute.attisdropped
WHERE view_class.relkind = 'v'
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
