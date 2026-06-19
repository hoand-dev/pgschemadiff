-- catalog/schemas.sql
-- Returns all user-defined schemas, excluding built-in system schemas.
-- Result columns:
--   schema_name  text  -- pg_namespace.nspname
SELECT
    nspname AS schema_name
FROM pg_catalog.pg_namespace
WHERE nspname NOT LIKE 'pg_%'
  AND nspname != 'information_schema'
ORDER BY nspname
