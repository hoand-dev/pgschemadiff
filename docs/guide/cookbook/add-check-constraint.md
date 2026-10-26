# Add a CHECK constraint

Use this to enforce a row-level invariant after checking existing data. Adding
and validating a CHECK constraint is DANGEROUS because PostgreSQL scans or
validates rows and may block or fail if data violates the expression.

```sql current
CREATE SCHEMA cookbook;
CREATE TABLE cookbook.users (id integer PRIMARY KEY, age integer);
```

```sql desired
CREATE SCHEMA cookbook;
CREATE TABLE cookbook.users (
    id integer PRIMARY KEY,
    age integer,
    CONSTRAINT users_age_check CHECK (age >= 0)
);
```

```text summary
d0001  dangerous    add_constraint    "cookbook"."users".users_age_check   Adding a constraint may scan or validate rows, block, or fail on existing data.
1 changes: safe=0 warning=0 dangerous=1 destructive=0 blocked=0
```

The migration adds the constraint `NOT VALID`, then validates it in a separate
transaction unit:

```sql up
ALTER TABLE "cookbook"."users" ADD CONSTRAINT "users_age_check" CHECK (age >= 0) NOT VALID
ALTER TABLE "cookbook"."users" VALIDATE CONSTRAINT "users_age_check"
```

Before applying, query for violating rows and resolve them. Use a lock timeout
suited to the table, then verify `convalidated`:

```sql
SELECT convalidated FROM pg_constraint
WHERE conrelid = 'cookbook.users'::regclass AND conname = 'users_age_check';
```
