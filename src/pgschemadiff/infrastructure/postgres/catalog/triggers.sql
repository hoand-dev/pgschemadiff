-- catalog/triggers.sql
-- Returns supported table triggers and their direct function/column metadata.
-- Selected-schema filtering is applied to the assembled rows in Python.
-- Result columns: schema_name, table_name, trigger_name, function_schema,
--                 function_name, function_input_types, referenced_table_schema,
--                 referenced_table_name, definition, timing, events, row_level,
--                 columns, when_expr, is_constraint, deferrable,
--                 initially_deferred, enabled
SELECT
    trigger_namespace.nspname AS schema_name,
    table_catalog.relname AS table_name,
    trigger_catalog.tgname AS trigger_name,
    function_namespace.nspname AS function_schema,
    trigger_function.proname AS function_name,
    ARRAY(
        SELECT pg_catalog.format_type(input_argument.type_oid, NULL)
        FROM pg_catalog.unnest(trigger_function.proargtypes)
            WITH ORDINALITY AS input_argument(type_oid, ordinal)
        ORDER BY input_argument.ordinal
    ) AS function_input_types,
    referenced_table_namespace.nspname AS referenced_table_schema,
    referenced_table_catalog.relname AS referenced_table_name,
    pg_catalog.pg_get_triggerdef(trigger_catalog.oid, true) AS definition,
    CASE
        WHEN (trigger_catalog.tgtype & 64) <> 0 THEN 'INSTEAD OF'
        WHEN (trigger_catalog.tgtype & 2) <> 0 THEN 'BEFORE'
        ELSE 'AFTER'
    END AS timing,
    ARRAY(
        SELECT trigger_event.event_name
        FROM (VALUES
            ('INSERT', 4, 1),
            ('DELETE', 8, 2),
            ('UPDATE', 16, 3),
            ('TRUNCATE', 32, 4)
        ) AS trigger_event(event_name, event_mask, event_order)
        WHERE (trigger_catalog.tgtype & trigger_event.event_mask) <> 0
        ORDER BY trigger_event.event_order
    ) AS events,
    (trigger_catalog.tgtype & 1) <> 0 AS row_level,
    ARRAY(
        SELECT trigger_attribute.attname
        FROM (
            SELECT update_column.attnum
            FROM pg_catalog.unnest(trigger_catalog.tgattr::smallint[])
                AS update_column(attnum)
            UNION
            SELECT column_dependency.refobjsubid::smallint
            FROM pg_catalog.pg_depend AS column_dependency
            WHERE column_dependency.classid = 'pg_catalog.pg_trigger'::regclass
              AND column_dependency.objid = trigger_catalog.oid
              AND column_dependency.refclassid = 'pg_catalog.pg_class'::regclass
              AND column_dependency.refobjid = trigger_catalog.tgrelid
              AND column_dependency.refobjsubid > 0
        ) AS referenced_column(attnum)
        JOIN pg_catalog.pg_attribute AS trigger_attribute
            ON trigger_attribute.attrelid = trigger_catalog.tgrelid
           AND trigger_attribute.attnum = referenced_column.attnum
           AND NOT trigger_attribute.attisdropped
        ORDER BY trigger_attribute.attnum
    ) AS columns,
    pg_catalog.pg_get_expr(trigger_catalog.tgqual, trigger_catalog.tgrelid, true) AS when_expr,
    trigger_catalog.tgconstraint <> 0 AS is_constraint,
    trigger_catalog.tgdeferrable AS deferrable,
    trigger_catalog.tginitdeferred AS initially_deferred,
    trigger_catalog.tgenabled AS enabled
FROM pg_catalog.pg_trigger AS trigger_catalog
JOIN pg_catalog.pg_class AS table_catalog
    ON table_catalog.oid = trigger_catalog.tgrelid
JOIN pg_catalog.pg_namespace AS trigger_namespace
    ON trigger_namespace.oid = table_catalog.relnamespace
JOIN pg_catalog.pg_proc AS trigger_function
    ON trigger_function.oid = trigger_catalog.tgfoid
JOIN pg_catalog.pg_namespace AS function_namespace
    ON function_namespace.oid = trigger_function.pronamespace
LEFT JOIN pg_catalog.pg_class AS referenced_table_catalog
    ON referenced_table_catalog.oid = trigger_catalog.tgconstrrelid
LEFT JOIN pg_catalog.pg_namespace AS referenced_table_namespace
    ON referenced_table_namespace.oid = referenced_table_catalog.relnamespace
WHERE table_catalog.relkind IN ('r', 'p')
  AND trigger_catalog.tgisinternal = false
  AND trigger_catalog.tgparentid = 0
  AND left(trigger_namespace.nspname, 3) != 'pg_'
  AND trigger_namespace.nspname != 'information_schema'
  AND trigger_namespace.nspname != 'pgschemadiff'
  AND NOT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_depend AS extension_dependency
      WHERE extension_dependency.classid = 'pg_catalog.pg_trigger'::regclass
        AND extension_dependency.objid = trigger_catalog.oid
        AND extension_dependency.deptype = 'e'
  )
ORDER BY trigger_namespace.nspname, table_catalog.relname, trigger_catalog.tgname;
