# Add an enum value

Use this to add a label accepted by an existing PostgreSQL enum. This is
DANGEROUS and irreversible: the accepted value set changes, and the tool does
not generate automatic rollback SQL.

```sql current
CREATE SCHEMA cookbook;
CREATE TYPE cookbook.account_status AS ENUM ('pending');
```

```sql desired
CREATE SCHEMA cookbook;
CREATE TYPE cookbook.account_status AS ENUM ('pending', 'suspended');
```

```text summary
d0001  dangerous    add_enum_value    "cookbook"."account_status"   Adds an enum label; this is irreversible and changes accepted values.
1 changes: safe=0 warning=0 dangerous=1 destructive=0 blocked=0
```

`up.sql` adds the label in its own execution unit:

```sql up
ALTER TYPE "cookbook"."account_status" ADD VALUE 'suspended'
```

Check PostgreSQL-version behavior and dependent application code before
applying. Confirm the label is present afterward:

```sql
SELECT enumlabel FROM pg_enum
WHERE enumtypid = 'cookbook.account_status'::regtype ORDER BY enumsortorder;
```
