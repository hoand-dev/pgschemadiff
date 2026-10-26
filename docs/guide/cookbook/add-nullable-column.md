# Add a nullable column

Use this for a new column that can remain `NULL` and has no default, identity,
or generated expression. This is classified SAFE.

```sql current
CREATE SCHEMA cookbook;
CREATE TABLE cookbook.users (id integer PRIMARY KEY);
```

```sql desired
CREATE SCHEMA cookbook;
CREATE TABLE cookbook.users (id integer PRIMARY KEY, nickname text);
```

```text summary
d0001  safe         add_column        "cookbook"."users".nickname   Adds a nullable column without a default, identity, or generated expression.
1 changes: safe=1 warning=0 dangerous=0 destructive=0 blocked=0
```

The generated `up.sql` adds the column without changing existing rows:

```sql up
ALTER TABLE "cookbook"."users" ADD COLUMN "nickname" text
```

Review the target and confirm application code accepts `NULL`. Apply with a
short lock timeout; verify the column exists and remains nullable:

```sql
SELECT is_nullable FROM information_schema.columns
WHERE table_schema = 'cookbook' AND table_name = 'users' AND column_name = 'nickname';
```
