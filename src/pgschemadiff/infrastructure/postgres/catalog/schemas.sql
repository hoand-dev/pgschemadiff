-- catalog/schemas.sql
-- Returns all user-defined schemas, excluding built-in system schemas.
-- Result columns:
--   schema_name  text  -- pg_namespace.nspname
--   owner        text  -- role owning the schema
--   comment      text  -- optional schema comment
SELECT
    n.nspname AS schema_name,
    pg_catalog.pg_get_userbyid(n.nspowner) AS owner,
    pg_catalog.obj_description(n.oid, 'pg_namespace') AS comment
FROM pg_catalog.pg_namespace AS n
WHERE left(n.nspname, 3) != 'pg_'
  AND n.nspname != 'information_schema'
  AND n.nspname != 'pgschemadiff'
ORDER BY n.nspname
