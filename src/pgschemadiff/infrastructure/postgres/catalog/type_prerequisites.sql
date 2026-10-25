-- catalog/type_prerequisites.sql
-- Returns enum/composite/domain types required by table columns, composite
-- attributes, domain base types, and function/procedure arguments/returns.
-- Array columns depend on their element type. System, reserved, and extension-owned
-- objects are excluded on both sides of each dependency.
-- Result columns:
--   dependent_kind   text -- table, composite_type, domain_type, function, or procedure
--   dependent_schema text -- schema owning the dependent object
--   dependent_name   text -- dependent table or composite type name
--   type_kind        text -- 'enum', 'composite_type', or 'domain_type'
--   type_schema      text -- schema owning the prerequisite type
--   type_name        text -- prerequisite type name
--   dependent_signature text[] -- routine input identity types, otherwise NULL
WITH dependent_columns AS (
    SELECT
        'table'::text AS dependent_kind,
        table_namespace.nspname AS dependent_schema,
        table_class.relname AS dependent_name,
        NULL::text[] AS dependent_signature,
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
      AND left(table_namespace.nspname, 3) != 'pg_'
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
        NULL::text[] AS dependent_signature,
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
      AND left(dependent_namespace.nspname, 3) != 'pg_'
      AND dependent_namespace.nspname != 'information_schema'
      AND dependent_namespace.nspname != 'pgschemadiff'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS d
          WHERE d.classid = 'pg_catalog.pg_type'::regclass
            AND d.objid = dependent_type.oid
            AND d.deptype = 'e'
      )

    UNION ALL

    SELECT
        'domain_type'::text AS dependent_kind,
        domain_namespace.nspname AS dependent_schema,
        domain_type.typname AS dependent_name,
        NULL::text[] AS dependent_signature,
        CASE
            WHEN base_type.typelem <> 0 THEN base_type.typelem
            ELSE domain_type.typbasetype
        END AS prerequisite_type_oid
    FROM pg_catalog.pg_type AS domain_type
    JOIN pg_catalog.pg_namespace AS domain_namespace
        ON domain_namespace.oid = domain_type.typnamespace
    JOIN pg_catalog.pg_type AS base_type
        ON base_type.oid = domain_type.typbasetype
    WHERE domain_type.typtype = 'd'
      AND left(domain_namespace.nspname, 3) != 'pg_'
      AND domain_namespace.nspname != 'information_schema'
      AND domain_namespace.nspname != 'pgschemadiff'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS d
          WHERE d.classid = 'pg_catalog.pg_type'::regclass
            AND d.objid = domain_type.oid
            AND d.deptype = 'e'
    )

    UNION ALL

    SELECT
        CASE routine.prokind WHEN 'p' THEN 'procedure' ELSE 'function' END AS dependent_kind,
        routine_namespace.nspname AS dependent_schema,
        routine.proname AS dependent_name,
        ARRAY(
            SELECT pg_catalog.format_type(input_argument.type_oid, NULL)
            FROM unnest(routine.proargtypes) WITH ORDINALITY
                AS input_argument(type_oid, ordinal)
            ORDER BY input_argument.ordinal
        ) AS dependent_signature,
        CASE
            WHEN referenced_type.typelem <> 0 THEN referenced_type.typelem
            ELSE referenced_type.oid
        END AS prerequisite_type_oid
    FROM pg_catalog.pg_proc AS routine
    JOIN pg_catalog.pg_namespace AS routine_namespace
        ON routine_namespace.oid = routine.pronamespace
    CROSS JOIN LATERAL (
        SELECT routine.prorettype AS type_oid
        UNION ALL
        SELECT all_argument.type_oid
        FROM unnest(COALESCE(routine.proallargtypes, routine.proargtypes::oid[]))
            AS all_argument(type_oid)
    ) AS routine_type
    JOIN pg_catalog.pg_type AS referenced_type
        ON referenced_type.oid = routine_type.type_oid
    WHERE routine.prokind IN ('f', 'p')
      AND left(routine_namespace.nspname, 3) != 'pg_'
      AND routine_namespace.nspname != 'information_schema'
      AND routine_namespace.nspname != 'pgschemadiff'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_dependency
          WHERE extension_dependency.classid = 'pg_catalog.pg_proc'::regclass
            AND extension_dependency.objid = routine.oid
            AND extension_dependency.deptype = 'e'
      )
)
SELECT DISTINCT
    dependencies.dependent_kind,
    dependencies.dependent_schema,
    dependencies.dependent_name,
    dependencies.dependent_signature,
    CASE prerequisite_type.typtype
        WHEN 'e' THEN 'enum'
        WHEN 'c' THEN 'composite_type'
        WHEN 'd' THEN 'domain_type'
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
        OR prerequisite_type.typtype = 'd'
    )
  AND left(prerequisite_namespace.nspname, 3) != 'pg_'
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
         dependencies.dependent_name, dependencies.dependent_signature, type_schema, type_name;
