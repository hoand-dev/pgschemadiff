-- catalog/domain_types.sql
-- Returns user domains, local checks, and whether any live table column reaches
-- the domain through an array, composite, range, or multirange container.
-- Result columns:
--   schema_name        text
--   domain_name        text
--   base_type          text -- format_type(typbasetype, typtypmod)
--   collation          text -- quoted catalog identifier, when applicable
--   default_expr       text -- pg_get_expr(typdefaultbin, 0)
--   not_null           boolean
--   check_name         text -- NULL when the domain has no local checks
--   check_expression   text -- pg_get_expr(conbin, 0)
--   check_validated    boolean
--   owner              text
--   used_in_container  boolean
WITH RECURSIVE type_walk(type_oid, inside_container, type_path) AS (
    SELECT
        a.atttypid,
        FALSE,
        ARRAY[a.atttypid]::oid[]
    FROM pg_catalog.pg_attribute AS a
    JOIN pg_catalog.pg_class AS owning_relation
        ON owning_relation.oid = a.attrelid
    JOIN pg_catalog.pg_namespace AS owning_namespace
        ON owning_namespace.oid = owning_relation.relnamespace
    WHERE owning_relation.relkind IN ('r', 'p')
      AND a.attnum > 0
      AND NOT a.attisdropped
      AND owning_namespace.nspname NOT LIKE 'pg_%'
      AND owning_namespace.nspname != 'information_schema'
      AND owning_namespace.nspname != 'pgschemadiff'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS relation_dependency
          WHERE relation_dependency.classid = 'pg_catalog.pg_class'::regclass
            AND relation_dependency.objid = owning_relation.oid
            AND relation_dependency.deptype = 'e'
      )

    UNION ALL

    SELECT
        next_type.type_oid,
        type_walk.inside_container OR next_type.is_container,
        type_walk.type_path || next_type.type_oid
    FROM type_walk
    JOIN pg_catalog.pg_type AS current_type
        ON current_type.oid = type_walk.type_oid
    JOIN LATERAL (
        SELECT current_type.typelem AS type_oid, TRUE AS is_container
        WHERE current_type.typelem <> 0

        UNION ALL

        SELECT attribute.atttypid AS type_oid, TRUE AS is_container
        FROM pg_catalog.pg_class AS composite_relation
        JOIN pg_catalog.pg_attribute AS attribute
            ON attribute.attrelid = composite_relation.oid
           AND attribute.attnum > 0
           AND NOT attribute.attisdropped
        WHERE current_type.typtype = 'c'
          AND composite_relation.oid = current_type.typrelid
          AND composite_relation.relkind = 'c'

        UNION ALL

        SELECT range_type.rngsubtype AS type_oid, TRUE AS is_container
        FROM pg_catalog.pg_range AS range_type
        WHERE range_type.rngtypid = current_type.oid
           OR range_type.rngmultitypid = current_type.oid

        UNION ALL

        SELECT current_type.typbasetype AS type_oid, FALSE AS is_container
        WHERE current_type.typtype = 'd'
          AND current_type.typbasetype <> 0
    ) AS next_type
        ON TRUE
    WHERE NOT next_type.type_oid = ANY(type_walk.type_path)
)
SELECT
    n.nspname AS schema_name,
    t.typname AS domain_name,
    pg_catalog.format_type(t.typbasetype, t.typtypmod) AS base_type,
    CASE
        WHEN t.typcollation = 0 THEN NULL
        WHEN collation_namespace.nspname = 'pg_catalog'
            THEN pg_catalog.format('%I', domain_collation.collname)
        ELSE pg_catalog.format('%I.%I', collation_namespace.nspname, domain_collation.collname)
    END AS collation,
    CASE
        WHEN t.typdefaultbin IS NULL THEN NULL
        ELSE pg_catalog.pg_get_expr(t.typdefaultbin, 0)
    END AS default_expr,
    t.typnotnull AS not_null,
    domain_check.conname AS check_name,
    pg_catalog.pg_get_expr(domain_check.conbin, 0) AS check_expression,
    domain_check.convalidated AS check_validated,
    pg_catalog.pg_get_userbyid(t.typowner) AS owner,
    EXISTS (
        SELECT 1
        FROM type_walk
        WHERE type_walk.type_oid = t.oid
          AND type_walk.inside_container
    ) AS used_in_container
FROM pg_catalog.pg_type AS t
JOIN pg_catalog.pg_namespace AS n
    ON n.oid = t.typnamespace
LEFT JOIN pg_catalog.pg_collation AS domain_collation
    ON domain_collation.oid = t.typcollation
LEFT JOIN pg_catalog.pg_namespace AS collation_namespace
    ON collation_namespace.oid = domain_collation.collnamespace
LEFT JOIN pg_catalog.pg_constraint AS domain_check
    ON domain_check.contypid = t.oid
   AND domain_check.contype = 'c'
   AND domain_check.conislocal
WHERE t.typtype = 'd'
  AND n.nspname NOT LIKE 'pg_%'
  AND n.nspname != 'information_schema'
  AND n.nspname != 'pgschemadiff'
  AND NOT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_depend AS domain_dependency
      WHERE domain_dependency.classid = 'pg_catalog.pg_type'::regclass
        AND domain_dependency.objid = t.oid
        AND domain_dependency.deptype = 'e'
  )
ORDER BY n.nspname, t.typname, domain_check.conname;
