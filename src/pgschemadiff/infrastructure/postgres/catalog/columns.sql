-- catalog/columns.sql
-- Returns all columns for user-defined tables and partitioned tables.
-- Excludes dropped columns (attisdropped) and system columns (attnum <= 0).
-- Excludes system schemas (pg_catalog, information_schema, pg_toast, pg_temp_*).
-- Result columns:
--   schema_name        text       -- owning schema
--   table_name         text       -- owning table
--   column_name        text       -- pg_attribute.attname
--   ordinal_position   int        -- 1-based column number (pg_attribute.attnum)
--   data_type          text       -- format_type(atttypid, atttypmod)
--   is_nullable        bool       -- true if column allows NULL (NOT attnotnull)
--   default_expr       text|null  -- pg_get_expr(adbin, adrelid) for DEFAULT, null otherwise
--   collation          text|null  -- SQL identifier fragment, qualified outside pg_catalog
--   is_identity        bool       -- true when attidentity != ''
--   identity_generated text|null  -- 'ALWAYS' or 'BY DEFAULT' (when is_identity), null otherwise
--   is_generated       bool       -- true when attgenerated = 's' (stored generated)
--   is_virtual_generated bool     -- true when attgenerated = 'v' (virtual generated)
--   generated_expr     text|null  -- pg_get_expr(adbin, adrelid) for stored/virtual generated cols
SELECT
    n.nspname                                            AS schema_name,
    c.relname                                            AS table_name,
    a.attname                                            AS column_name,
    a.attnum                                             AS ordinal_position,
    format_type(a.atttypid, a.atttypmod)                AS data_type,
    NOT a.attnotnull                                     AS is_nullable,
    CASE
        WHEN a.attgenerated <> '' THEN NULL
        WHEN ad.adbin IS NOT NULL
            THEN pg_get_expr(ad.adbin, ad.adrelid)
        ELSE NULL
    END                                                  AS default_expr,
    CASE
        WHEN a.attcollation <> 0
             AND a.attcollation <> t.typcollation
            THEN CASE
                WHEN collation_namespace.nspname = 'pg_catalog'
                    THEN format('%I', col.collname)
                ELSE format('%I.%I', collation_namespace.nspname, col.collname)
            END
        ELSE NULL
    END                                                  AS collation,
    a.attidentity != ''                                  AS is_identity,
    CASE a.attidentity
        WHEN 'a' THEN 'ALWAYS'
        WHEN 'd' THEN 'BY DEFAULT'
        ELSE NULL
    END                                                  AS identity_generated,
    a.attgenerated = 's'                                 AS is_generated,
    a.attgenerated = 'v'                                 AS is_virtual_generated,
    CASE
        WHEN a.attgenerated IN ('s', 'v') AND ad.adbin IS NOT NULL
            THEN pg_get_expr(ad.adbin, ad.adrelid)
        ELSE NULL
    END                                                  AS generated_expr
FROM pg_catalog.pg_attribute a
JOIN pg_catalog.pg_class c
    ON c.oid = a.attrelid
JOIN pg_catalog.pg_namespace n
    ON n.oid = c.relnamespace
JOIN pg_catalog.pg_type t
    ON t.oid = a.atttypid
LEFT JOIN pg_catalog.pg_attrdef ad
    ON ad.adrelid = a.attrelid
   AND ad.adnum   = a.attnum
LEFT JOIN pg_catalog.pg_collation col
    ON col.oid = a.attcollation
LEFT JOIN pg_catalog.pg_namespace collation_namespace
    ON collation_namespace.oid = col.collnamespace
WHERE c.relkind IN ('r', 'p')
  AND a.attnum > 0
  AND NOT a.attisdropped
  AND left(n.nspname, 3) != 'pg_'
  AND n.nspname != 'information_schema'
  AND n.nspname != 'pgschemadiff'
ORDER BY n.nspname, c.relname, a.attnum
