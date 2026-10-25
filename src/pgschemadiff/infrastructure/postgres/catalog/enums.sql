-- catalog/enums.sql
-- Returns non-extension-owned enum types and labels in PostgreSQL sort order.
-- Result columns:
--   schema_name text       -- owning schema
--   enum_name   text       -- pg_type.typname
--   labels      text[]     -- labels ordered by pg_enum.enumsortorder
--   owner       text|null  -- role owning the enum type
SELECT
    n.nspname AS schema_name,
    t.typname AS enum_name,
    COALESCE(
        array_agg(e.enumlabel ORDER BY e.enumsortorder)
            FILTER (WHERE e.enumlabel IS NOT NULL),
        '{}'::text[]
    ) AS labels,
    pg_catalog.pg_get_userbyid(t.typowner) AS owner
FROM pg_catalog.pg_type AS t
JOIN pg_catalog.pg_namespace AS n
    ON n.oid = t.typnamespace
-- LEFT JOIN: PostgreSQL allows enums with no labels.
LEFT JOIN pg_catalog.pg_enum AS e
    ON e.enumtypid = t.oid
WHERE t.typtype = 'e'
  AND n.nspname NOT LIKE 'pg_%'
  AND n.nspname != 'information_schema'
  AND n.nspname != 'pgschemadiff'
  AND NOT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_depend AS d
      WHERE d.classid = 'pg_catalog.pg_type'::regclass
        AND d.objid = t.oid
        AND d.deptype = 'e'
  )
GROUP BY n.nspname, t.typname, t.typowner
ORDER BY n.nspname, t.typname;
