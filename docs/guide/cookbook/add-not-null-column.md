# Add a NOT NULL column with a default

Use this when new rows need a default value and the column must be non-null.
The change is WARNING: PostgreSQL may rewrite or validate existing rows,
depending on server version and the default.

```sql current
CREATE SCHEMA cookbook;
CREATE TABLE cookbook.users (id integer PRIMARY KEY);
```

```sql desired
CREATE SCHEMA cookbook;
CREATE TABLE cookbook.users (id integer PRIMARY KEY, status integer NOT NULL DEFAULT 0);
```

```text summary
d0001  warning      add_column        "cookbook"."users".status   Adds a column with NOT NULL, a default; existing rows may require rewrite or validation.
1 changes: safe=0 warning=1 dangerous=0 destructive=0 blocked=0
```

`up.sql` adds the default before the nullability constraint:

```sql up
ALTER TABLE "cookbook"."users" ADD COLUMN "status" integer DEFAULT 0 NOT NULL
```

On a large table, test against representative data and PostgreSQL version
first. Use a reviewed lock timeout. Verify nullability and default:

```sql
SELECT is_nullable, column_default FROM information_schema.columns
WHERE table_schema = 'cookbook' AND table_name = 'users' AND column_name = 'status';
```
