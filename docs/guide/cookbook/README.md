# Safe-migration cookbook

Each recipe includes current and desired schemas, the exact CLI summary, an
`up.sql` excerpt, and operational checks. The recipes run through the actual
CLI in the integration suite so summaries and SQL excerpts stay aligned with
implemented behavior.

| Recipe | Scenario | Risk |
|---|---|---|
| [Add a nullable column](add-nullable-column.md) | Add a column without a default. | SAFE |
| [Add a NOT NULL column](add-not-null-column.md) | Add a column with a default and NOT NULL. | WARNING |
| [Create an index](create-index.md) | Create a standalone concurrent index. | WARNING |
| [Add a CHECK constraint](add-check-constraint.md) | Add `NOT VALID`, then validate. | DANGEROUS |
| [Widen a column type](widen-column-type.md) | Convert `integer` to `bigint`. | DANGEROUS |
| [Rename a column](rename-column.md) | Use an explicit rename annotation. | WARNING |
| [Drop a column](drop-column.md) | Review destructive data removal and approval. | DESTRUCTIVE |
| [Add an enum value](add-enum-value.md) | Add an irreversible enum label. | DANGEROUS |
| [Enable row-level security](row-level-security.md) | Add a policy and enable RLS. | DANGEROUS |

The rename example uses `--renames` with YAML. The CLI also accepts the same
document shape in TOML; see [the CLI reference](../cli.md#rename-file-formats).
All examples use the `cookbook` schema and `CURRENT_USER` where a role is
needed; they contain no real credentials.
