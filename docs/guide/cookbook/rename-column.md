# Rename a column explicitly

Use an explicit rename annotation when a column keeps its data but changes
name. Without the annotation, the diff sees a drop and an add. This rename is
WARNING because it requires a lock and can break dependent application code.

```sql current
CREATE SCHEMA cookbook;
CREATE TABLE cookbook.users (old_email text);
```

```sql desired
CREATE SCHEMA cookbook;
CREATE TABLE cookbook.users (email text);
```

Pass this YAML file to both `diff` and `generate` with `--renames`:

```yaml renames
renames:
  - kind: column
    from: cookbook.users.old_email
    to: cookbook.users.email
```

```text summary
d0001  warning      rename_column     "cookbook"."users".old_email   Column rename requires a lock and can affect dependent application behavior.
1 changes: safe=0 warning=1 dangerous=0 destructive=0 blocked=0
```

The generated SQL preserves the column's data:

```sql up
ALTER TABLE "cookbook"."users" RENAME COLUMN "old_email" TO "email"
```

Deploy compatible application code before or alongside the rename, after
checking dependencies. Verify the new name and expected row count:

```sql
SELECT count(*) FROM cookbook.users WHERE email IS NOT NULL;
```
