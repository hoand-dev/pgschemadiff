-- catalog/extensions.sql
-- Returns all currently installed PostgreSQL extensions and their metadata.
-- Result columns:
--   extension_name     text  -- extension name
--   installed_version  text  -- currently installed version
--   installed_schema   text  -- schema containing extension objects
--   comment            text  -- optional extension comment
SELECT
    e.extname AS extension_name,
    e.extversion AS installed_version,
    n.nspname AS installed_schema,
    pg_catalog.obj_description(e.oid, 'pg_extension') AS comment
FROM pg_catalog.pg_extension AS e
LEFT JOIN pg_catalog.pg_namespace AS n ON n.oid = e.extnamespace
ORDER BY e.extname
