-- catalog/composite_types.sql
-- Returns standalone, non-extension-owned composite types and live attributes.
-- Table row types are excluded by requiring the backing relation kind 'c'.
-- Result columns:
--   schema_name     text       -- owning schema
--   type_name       text       -- composite type name
--   attribute_position int|null -- pg_attribute.attnum
--   attribute_name  text|null  -- NULL for an empty composite
--   data_type       text|null  -- format_type(atttypid, atttypmod)
--   collation       text|null  -- SQL identifier fragment for explicit collation
--   owner           text       -- role owning the composite type
SELECT
    n.nspname AS schema_name,
    t.typname AS type_name,
    a.attnum AS attribute_position,
    a.attname AS attribute_name,
    pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
    CASE
        WHEN a.attcollation <> 0
             AND a.attcollation <> attribute_type.typcollation
            THEN CASE
                WHEN collation_namespace.nspname = 'pg_catalog'
                    THEN pg_catalog.format('%I', col.collname)
                ELSE pg_catalog.format('%I.%I', collation_namespace.nspname, col.collname)
            END
        ELSE NULL
    END AS collation,
    pg_catalog.pg_get_userbyid(t.typowner) AS owner
FROM pg_catalog.pg_type AS t
JOIN pg_catalog.pg_namespace AS n
    ON n.oid = t.typnamespace
JOIN pg_catalog.pg_class AS composite_relation
    ON composite_relation.oid = t.typrelid
   AND composite_relation.relkind = 'c'
LEFT JOIN pg_catalog.pg_attribute AS a
    ON a.attrelid = composite_relation.oid
   AND a.attnum > 0
   AND NOT a.attisdropped
LEFT JOIN pg_catalog.pg_type AS attribute_type
    ON attribute_type.oid = a.atttypid
LEFT JOIN pg_catalog.pg_collation AS col
    ON col.oid = a.attcollation
LEFT JOIN pg_catalog.pg_namespace AS collation_namespace
    ON collation_namespace.oid = col.collnamespace
WHERE t.typtype = 'c'
  AND left(n.nspname, 3) != 'pg_'
  AND n.nspname != 'information_schema'
  AND n.nspname != 'pgschemadiff'
  AND NOT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_depend AS d
      WHERE d.classid = 'pg_catalog.pg_type'::regclass
        AND d.objid = t.oid
        AND d.deptype = 'e'
  )
ORDER BY n.nspname, t.typname, a.attnum;
