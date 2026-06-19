-- catalog/extensions.sql
-- Returns all currently installed PostgreSQL extensions.
-- Source: pg_available_extensions view (built-in, no extra joins needed).
-- Result columns:
--   extension_name     text  -- extension name
--   default_version    text  -- version that would be installed by default
--   installed_version  text  -- currently installed version
SELECT
    name              AS extension_name,
    default_version,
    installed_version
FROM pg_catalog.pg_available_extensions
WHERE installed_version IS NOT NULL
ORDER BY name
