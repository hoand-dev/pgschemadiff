# Create an index

Use this to add a standalone index. The emitted create statement uses
`CONCURRENTLY`, so the unit is non-transactional and cannot be rolled back.
The change is WARNING because execution mode can affect blocking.

```sql current
CREATE SCHEMA cookbook;
CREATE TABLE cookbook.users (email text);
```

```sql desired
CREATE SCHEMA cookbook;
CREATE TABLE cookbook.users (email text);
CREATE INDEX users_email_idx ON cookbook.users USING btree (email);
```

```text summary
d0001  warning      create_index      "cookbook"."users_email_idx"   Index creation may block because execution mode is not specified.
1 changes: safe=0 warning=1 dangerous=0 destructive=0 blocked=0
```

The generated statement runs outside a transaction:

```sql up
CREATE INDEX CONCURRENTLY users_email_idx ON cookbook.users USING btree (email)
```

Schedule for acceptable load and keep lock/statement timeout choices under
review. If interrupted, check for and drop an INVALID index before retrying:

```sql
SELECT indexrelid::regclass, indisvalid FROM pg_index
WHERE indexrelid = 'cookbook.users_email_idx'::regclass;
```
