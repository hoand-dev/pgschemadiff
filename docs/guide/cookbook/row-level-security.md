# Enable row-level security and add a policy

Use this when access should be controlled by a PostgreSQL row-level security
policy. This is DANGEROUS because it changes which rows application roles can
read or modify.

```sql current
CREATE SCHEMA cookbook;
CREATE TABLE cookbook.users (id integer PRIMARY KEY);
```

```sql desired
CREATE SCHEMA cookbook;
CREATE TABLE cookbook.users (id integer PRIMARY KEY);
ALTER TABLE cookbook.users ENABLE ROW LEVEL SECURITY;
CREATE POLICY users_policy ON cookbook.users TO CURRENT_USER USING (true);
```

```text summary
d0001  dangerous    create_policy     "cookbook"."users".users_policy   Changes row-level security access behavior.
d0002  dangerous    alter_table_attrs  "cookbook"."users"   Changes row-level security access behavior.
2 changes: safe=0 warning=0 dangerous=2 destructive=0 blocked=0
```

`CURRENT_USER` resolves to the actual role in the desired database, and the
generated `TO` clause quotes that role name. Review it, ordering, and policy
expressions against the application's actual roles:

```sql up
CREATE POLICY "users_policy" ON "cookbook"."users" AS PERMISSIVE FOR ALL
ALTER TABLE "cookbook"."users" ENABLE ROW LEVEL SECURITY
```

Test as each relevant role before rollout. Verify the policy and table flag:

```sql
SELECT relrowsecurity FROM pg_class WHERE oid = 'cookbook.users'::regclass;
SELECT policyname, roles, qual FROM pg_policies
WHERE schemaname = 'cookbook' AND tablename = 'users';
```
