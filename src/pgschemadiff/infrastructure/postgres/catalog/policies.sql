-- catalog/policies.sql
-- Returns policies attached to user-defined ordinary and partitioned tables.
SELECT
    n.nspname AS schema_name,
    c.relname AS table_name,
    p.polname AS policy_name,
    CASE p.polcmd
        WHEN '*' THEN 'ALL'
        WHEN 'r' THEN 'SELECT'
        WHEN 'a' THEN 'INSERT'
        WHEN 'w' THEN 'UPDATE'
        WHEN 'd' THEN 'DELETE'
        ELSE p.polcmd::text
    END AS command,
    p.polpermissive AS permissive,
    policy_roles.roles,
    pg_catalog.pg_get_expr(p.polqual, p.polrelid) AS using_expr,
    pg_catalog.pg_get_expr(p.polwithcheck, p.polrelid) AS with_check_expr
FROM pg_catalog.pg_policy AS p
JOIN pg_catalog.pg_class AS c
    ON c.oid = p.polrelid
JOIN pg_catalog.pg_namespace AS n
    ON n.oid = c.relnamespace
CROSS JOIN LATERAL (
    SELECT array_agg(role_name ORDER BY role_name) AS roles
    FROM (
        SELECT CASE
            WHEN role_oid = 0::oid THEN 'public'
            ELSE pg_catalog.pg_get_userbyid(role_oid)
        END AS role_name
        FROM unnest(p.polroles) AS policy_role(role_oid)
    ) AS resolved_roles
) AS policy_roles
WHERE c.relkind IN ('r', 'p')
  AND left(n.nspname, 3) != 'pg_'
  AND n.nspname != 'information_schema'
  AND n.nspname != 'pgschemadiff'
  -- Policies on extension-owned relations are independently managed state.
  AND NOT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_depend AS d
      WHERE d.classid = 'pg_catalog.pg_policy'::regclass
        AND d.objid = p.oid
        AND d.deptype = 'e'
  )
ORDER BY n.nspname, c.relname, p.polname;
