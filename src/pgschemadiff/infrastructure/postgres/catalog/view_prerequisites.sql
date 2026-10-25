-- catalog/view_prerequisites.sql
-- Returns dependencies recorded for view and materialized-view rewrite rules.
-- Extension members and system objects are excluded; selected-schema filtering
-- stays in Python.
-- Result columns: dependent_schema, dependent_name, prerequisite_kind,
--                 prerequisite_schema, prerequisite_name, prerequisite_signature
WITH view_dependencies AS (
    SELECT
        view_namespace.nspname AS dependent_schema,
        view_class.relname AS dependent_name,
        dependency.refclassid,
        dependency.refobjid,
        view_class.oid AS dependent_oid
    FROM pg_catalog.pg_rewrite AS view_rewrite
    JOIN pg_catalog.pg_class AS view_class
        ON view_class.oid = view_rewrite.ev_class
    JOIN pg_catalog.pg_namespace AS view_namespace
        ON view_namespace.oid = view_class.relnamespace
    JOIN pg_catalog.pg_depend AS dependency
        ON dependency.classid = 'pg_catalog.pg_rewrite'::regclass
       AND dependency.objid = view_rewrite.oid
    WHERE view_rewrite.rulename = '_RETURN'
      AND view_class.relkind IN ('v', 'm')
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
)
SELECT DISTINCT
    view_dependencies.dependent_schema,
    view_dependencies.dependent_name,
    CASE
        WHEN view_dependencies.refclassid = 'pg_catalog.pg_class'::regclass
             AND prerequisite_relation.relkind IN ('r', 'p') THEN 'table'
        WHEN view_dependencies.refclassid = 'pg_catalog.pg_class'::regclass
              AND prerequisite_relation.relkind = 'v' THEN 'view'
        WHEN view_dependencies.refclassid = 'pg_catalog.pg_class'::regclass
              AND prerequisite_relation.relkind = 'm' THEN 'materialized_view'
        WHEN view_dependencies.refclassid = 'pg_catalog.pg_class'::regclass
             AND prerequisite_relation.relkind = 'S' THEN 'sequence'
        WHEN view_dependencies.refclassid = 'pg_catalog.pg_proc'::regclass
             AND prerequisite_routine.prokind = 'f' THEN 'function'
        WHEN view_dependencies.refclassid = 'pg_catalog.pg_proc'::regclass
             AND prerequisite_routine.prokind = 'p' THEN 'procedure'
        WHEN view_dependencies.refclassid = 'pg_catalog.pg_type'::regclass
             AND prerequisite_type.typtype = 'e' THEN 'enum'
        WHEN view_dependencies.refclassid = 'pg_catalog.pg_type'::regclass
             AND prerequisite_type.typtype = 'd' THEN 'domain_type'
        WHEN view_dependencies.refclassid = 'pg_catalog.pg_type'::regclass
             AND prerequisite_type.typtype = 'c'
             AND prerequisite_type_relation.relkind = 'c' THEN 'composite_type'
    END AS prerequisite_kind,
    COALESCE(
        prerequisite_namespace.nspname,
        routine_namespace.nspname,
        type_namespace.nspname
    ) AS prerequisite_schema,
    COALESCE(
        prerequisite_relation.relname,
        prerequisite_routine.proname,
        prerequisite_type.typname
    ) AS prerequisite_name,
    CASE
        WHEN prerequisite_routine.oid IS NOT NULL THEN ARRAY(
            SELECT pg_catalog.format_type(input_argument.type_oid, NULL)
            FROM pg_catalog.unnest(prerequisite_routine.proargtypes)
                WITH ORDINALITY AS input_argument(type_oid, ordinal)
            ORDER BY input_argument.ordinal
        )
        ELSE NULL::text[]
    END AS prerequisite_signature
FROM view_dependencies
LEFT JOIN pg_catalog.pg_class AS prerequisite_relation
    ON view_dependencies.refclassid = 'pg_catalog.pg_class'::regclass
   AND prerequisite_relation.oid = view_dependencies.refobjid
LEFT JOIN pg_catalog.pg_namespace AS prerequisite_namespace
    ON prerequisite_namespace.oid = prerequisite_relation.relnamespace
LEFT JOIN pg_catalog.pg_proc AS prerequisite_routine
    ON view_dependencies.refclassid = 'pg_catalog.pg_proc'::regclass
   AND prerequisite_routine.oid = view_dependencies.refobjid
LEFT JOIN pg_catalog.pg_namespace AS routine_namespace
    ON routine_namespace.oid = prerequisite_routine.pronamespace
LEFT JOIN pg_catalog.pg_type AS referenced_type
    ON view_dependencies.refclassid = 'pg_catalog.pg_type'::regclass
   AND referenced_type.oid = view_dependencies.refobjid
LEFT JOIN pg_catalog.pg_type AS prerequisite_type
    ON prerequisite_type.oid = CASE
        WHEN referenced_type.typelem <> 0 THEN referenced_type.typelem
        ELSE referenced_type.oid
    END
LEFT JOIN pg_catalog.pg_namespace AS type_namespace
    ON type_namespace.oid = prerequisite_type.typnamespace
LEFT JOIN pg_catalog.pg_class AS prerequisite_type_relation
    ON prerequisite_type_relation.oid = prerequisite_type.typrelid
WHERE NOT (
        view_dependencies.refclassid = 'pg_catalog.pg_class'::regclass
        AND view_dependencies.refobjid = view_dependencies.dependent_oid
    )
  AND (
      (
           prerequisite_relation.relkind IN ('r', 'p', 'v', 'm', 'S')
          AND left(prerequisite_namespace.nspname, 3) != 'pg_'
          AND prerequisite_namespace.nspname != 'information_schema'
          AND prerequisite_namespace.nspname != 'pgschemadiff'
          AND NOT EXISTS (
              SELECT 1
              FROM pg_catalog.pg_depend AS extension_dependency
              WHERE extension_dependency.classid = 'pg_catalog.pg_class'::regclass
                AND extension_dependency.objid = prerequisite_relation.oid
                AND extension_dependency.deptype = 'e'
          )
      )
      OR (
          prerequisite_routine.prokind IN ('f', 'p')
          AND left(routine_namespace.nspname, 3) != 'pg_'
          AND routine_namespace.nspname != 'information_schema'
          AND routine_namespace.nspname != 'pgschemadiff'
          AND NOT EXISTS (
              SELECT 1
              FROM pg_catalog.pg_depend AS extension_dependency
              WHERE extension_dependency.classid = 'pg_catalog.pg_proc'::regclass
                AND extension_dependency.objid = prerequisite_routine.oid
                AND extension_dependency.deptype = 'e'
          )
      )
      OR (
          (
              prerequisite_type.typtype IN ('e', 'd')
              OR (
                  prerequisite_type.typtype = 'c'
                  AND prerequisite_type_relation.relkind = 'c'
              )
          )
          AND left(type_namespace.nspname, 3) != 'pg_'
          AND type_namespace.nspname != 'information_schema'
          AND type_namespace.nspname != 'pgschemadiff'
          AND NOT EXISTS (
              SELECT 1
              FROM pg_catalog.pg_depend AS extension_dependency
              WHERE extension_dependency.classid = 'pg_catalog.pg_type'::regclass
                AND extension_dependency.objid = prerequisite_type.oid
                AND extension_dependency.deptype = 'e'
          )
      )
  )
ORDER BY
    view_dependencies.dependent_schema,
    view_dependencies.dependent_name,
    prerequisite_kind,
    prerequisite_schema,
    prerequisite_name,
    prerequisite_signature;
