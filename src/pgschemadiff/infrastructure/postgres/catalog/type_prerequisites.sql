-- catalog/type_prerequisites.sql
-- Returns enum/composite types required by table columns and composite attributes.
-- Array columns depend on their element type. System, reserved, and extension-owned
-- objects are excluded on both sides of each dependency.
-- Result columns:
--   dependent_kind   text -- 'table' or 'composite_type'
--   dependent_schema text -- schema owning the dependent object
--   dependent_name   text -- dependent table or composite type name
--   type_kind        text -- 'enum' or 'composite_type'
--   type_schema      text -- schema owning the prerequisite type
--   type_name        text -- prerequisite type name
WITH dependent_columns AS (
    SELECT
        'table'::text AS dependent_kind,
        table_namespace.nspname AS dependent_schema,
        table_class.relname AS dependent_name,
        CASE WHEN column_type.typelem <> 0 THEN column_type.typelem ELSE column_type.oid END
            AS prerequisite_type_oid
    FROM pg_catalog.pg_attribute AS a
    JOIN pg_catalog.pg_class AS table_class
        ON table_class.oid = a.attrelid
    JOIN pg_catalog.pg_namespace AS table_namespace
        ON table_namespace.oid = table_class.relnamespace
    JOIN pg_catalog.pg_type AS column_type
        ON column_type.oid = a.atttypid
    WHERE table_class.relkind IN ('r', 'p')
      AND a.attnum > 0
      AND NOT a.attisdropped
      AND table_namespace.nspname NOT LIKE 'pg_%'
      AND table_namespace.nspname != 'information_schema'
      AND table_namespace.nspname != 'pgschemadiff'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS d
          WHERE d.classid = 'pg_catalog.pg_class'::regclass
            AND d.objid = table_class.oid
            AND d.deptype = 'e'
      )

    UNION ALL

    SELECT
        'composite_type'::text AS dependent_kind,
        dependent_namespace.nspname AS dependent_schema,
        dependent_type.typname AS dependent_name,
        CASE WHEN attribute_type.typelem <> 0 THEN attribute_type.typelem ELSE attribute_type.oid END
            AS prerequisite_type_oid
    FROM pg_catalog.pg_type AS dependent_type
    JOIN pg_catalog.pg_class AS composite_relation
        ON composite_relation.oid = dependent_type.typrelid
       AND composite_relation.relkind = 'c'
    JOIN pg_catalog.pg_namespace AS dependent_namespace
        ON dependent_namespace.oid = dependent_type.typnamespace
    JOIN pg_catalog.pg_attribute AS a
        ON a.attrelid = composite_relation.oid
       AND a.attnum > 0
       AND NOT a.attisdropped
    JOIN pg_catalog.pg_type AS attribute_type
        ON attribute_type.oid = a.atttypid
    WHERE dependent_type.typtype = 'c'
      AND dependent_namespace.nspname NOT LIKE 'pg_%'
      AND dependent_namespace.nspname != 'information_schema'
      AND dependent_namespace.nspname != 'pgschemadiff'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS d
          WHERE d.classid = 'pg_catalog.pg_type'::regclass
            AND d.objid = dependent_type.oid
            AND d.deptype = 'e'
      )
)
SELECT DISTINCT
    dependencies.dependent_kind,
    dependencies.dependent_schema,
    dependencies.dependent_name,
    CASE prerequisite_type.typtype
        WHEN 'e' THEN 'enum'
        WHEN 'c' THEN 'composite_type'
    END AS type_kind,
    prerequisite_namespace.nspname AS type_schema,
    prerequisite_type.typname AS type_name
FROM dependent_columns AS dependencies
JOIN pg_catalog.pg_type AS prerequisite_type
    ON prerequisite_type.oid = dependencies.prerequisite_type_oid
JOIN pg_catalog.pg_namespace AS prerequisite_namespace
    ON prerequisite_namespace.oid = prerequisite_type.typnamespace
LEFT JOIN pg_catalog.pg_class AS prerequisite_relation
    ON prerequisite_relation.oid = prerequisite_type.typrelid
WHERE (
        prerequisite_type.typtype = 'e'
        OR (prerequisite_type.typtype = 'c' AND prerequisite_relation.relkind = 'c')
    )
  AND prerequisite_namespace.nspname NOT LIKE 'pg_%'
  AND prerequisite_namespace.nspname != 'information_schema'
  AND prerequisite_namespace.nspname != 'pgschemadiff'
  AND NOT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_depend AS d
      WHERE d.classid = 'pg_catalog.pg_type'::regclass
        AND d.objid = prerequisite_type.oid
        AND d.deptype = 'e'
  )
ORDER BY dependencies.dependent_kind, dependencies.dependent_schema,
         dependencies.dependent_name, type_schema, type_name;
