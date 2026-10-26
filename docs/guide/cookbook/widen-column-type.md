# Widen an integer column to bigint

Use this when the target schema changes an `integer` column to `bigint`. The
change is DANGEROUS: a type conversion can rewrite the table and hold a long
lock.

```sql current
CREATE SCHEMA cookbook;
CREATE TABLE cookbook.users (amount integer);
```

```sql desired
CREATE SCHEMA cookbook;
CREATE TABLE cookbook.users (amount bigint);
```

```text summary
d0001  dangerous    alter_column_type  "cookbook"."users".amount   Type conversion may rewrite the table and hold a long lock.
1 changes: safe=0 warning=0 dangerous=1 destructive=0 blocked=0
```

The generated statement changes the column type directly:

```sql up
ALTER TABLE "cookbook"."users" ALTER COLUMN "amount" TYPE bigint
```

Although integer-to-bigint is a widening conversion, estimate table size,
replication impact, and lock duration before applying. Verify the catalog type:

```sql
SELECT data_type FROM information_schema.columns
WHERE table_schema = 'cookbook' AND table_name = 'users' AND column_name = 'amount';
```
