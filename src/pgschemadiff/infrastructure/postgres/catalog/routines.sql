-- catalog/routines.sql
-- Returns user-defined functions and procedures; aggregate/window routines and
-- extension members are excluded. PostgreSQL 18 proargtypes contains only
-- IN/INOUT/VARIADIC types. DROP PROCEDURE resolves from those input types and
-- ignores OUT types (see catalog-pg-proc.html and sql-dropprocedure.html).
-- Defaults remain an opaque deparsed argument list; no SQL parser is needed.
-- Result columns:
--   routine_kind, schema_name, function_name, input_types, all_argument_types, argument_modes,
--   argument_names, default_expressions, default_count, return_type, returns_set,
--   language, volatility, strict, security_definer, leakproof, parallel, cost,
--   rows, support_function, transforms, config, body, definition, owner
SELECT
    routine.prokind AS routine_kind,
    routine_namespace.nspname AS schema_name,
    routine.proname AS function_name,
    ARRAY(
        SELECT pg_catalog.format_type(input_argument.type_oid, NULL)
        FROM unnest(routine.proargtypes) WITH ORDINALITY AS input_argument(type_oid, ordinal)
        ORDER BY input_argument.ordinal
    ) AS input_types,
    ARRAY(
        SELECT pg_catalog.format_type(all_argument.type_oid, NULL)
        FROM unnest(COALESCE(routine.proallargtypes, routine.proargtypes::oid[]))
            WITH ORDINALITY AS all_argument(type_oid, ordinal)
        ORDER BY all_argument.ordinal
    ) AS all_argument_types,
    COALESCE(
        routine.proargmodes,
        ARRAY(
            SELECT 'i'::"char"
            FROM unnest(routine.proargtypes) WITH ORDINALITY AS input_argument(type_oid, ordinal)
            ORDER BY input_argument.ordinal
        )
    ) AS argument_modes,
    routine.proargnames AS argument_names,
    pg_catalog.pg_get_expr(routine.proargdefaults, 0) AS default_expressions,
    routine.pronargdefaults AS default_count,
    pg_catalog.format_type(routine.prorettype, NULL) AS return_type,
    routine.proretset AS returns_set,
    function_language.lanname AS language,
    CASE routine.provolatile
        WHEN 'i' THEN 'immutable'
        WHEN 's' THEN 'stable'
        WHEN 'v' THEN 'volatile'
    END AS volatility,
    routine.proisstrict AS strict,
    routine.prosecdef AS security_definer,
    routine.proleakproof AS leakproof,
    CASE routine.proparallel
        WHEN 'u' THEN 'unsafe'
        WHEN 'r' THEN 'restricted'
        WHEN 's' THEN 'safe'
    END AS parallel,
    routine.procost AS cost,
    routine.prorows AS rows,
    CASE
        WHEN routine.prosupport = 0 THEN NULL
        ELSE routine.prosupport::pg_catalog.regproc::text
    END AS support_function,
    ARRAY(
        SELECT pg_catalog.format_type(transform_type.type_oid, NULL)
        FROM unnest(routine.protrftypes) WITH ORDINALITY AS transform_type(type_oid, ordinal)
        ORDER BY transform_type.ordinal
    ) AS transforms,
    routine.proconfig AS config,
    routine.prosrc AS body,
    pg_catalog.pg_get_functiondef(routine.oid) AS definition,
    pg_catalog.pg_get_userbyid(routine.proowner) AS owner
FROM pg_catalog.pg_proc AS routine
JOIN pg_catalog.pg_namespace AS routine_namespace
    ON routine_namespace.oid = routine.pronamespace
JOIN pg_catalog.pg_language AS function_language
    ON function_language.oid = routine.prolang
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
ORDER BY routine_namespace.nspname, routine.proname, input_types;
