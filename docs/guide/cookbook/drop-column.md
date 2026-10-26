# Drop a column

Use only after confirming that no application or database dependency needs the
column. Dropping it is DESTRUCTIVE and permanently removes its data.

```sql current
CREATE SCHEMA cookbook;
CREATE TABLE cookbook.users (obsolete text);
```

```sql desired
CREATE SCHEMA cookbook;
CREATE TABLE cookbook.users ();
```

```text summary
d0001  destructive  drop_column       "cookbook"."users".obsolete   Removes column data.
1 changes: safe=0 warning=0 dangerous=0 destructive=1 blocked=0
```

The bundle drops the column; it does not preserve or reconstruct its values:

```sql up
ALTER TABLE "cookbook"."users" DROP COLUMN "obsolete"
```

Back up or archive required data first. `generate` must allow destructive risk,
and `apply` requires explicit approval with `--yes` (or an interactive
confirmation). Review the bundle before approving. Verify the column is gone:

```sql
SELECT column_name FROM information_schema.columns
WHERE table_schema = 'cookbook' AND table_name = 'users';
```
