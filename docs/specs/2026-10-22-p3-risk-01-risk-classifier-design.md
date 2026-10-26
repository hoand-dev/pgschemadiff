# P3-RISK-01 — Risk classifier design

**Status:** Design sections approved in chat; written spec pending user review.
**Date:** 2026-10-22

## Goal

Classify every schema delta with a stable five-level operational risk and a
human-readable reason. Keep risk metadata outside domain deltas so the diff
contract remains unchanged, while letting migration generation reject
unacceptable or unclassified changes.

## Decisions

- Keep all existing domain delta models unchanged.
- Put `RiskLevel`, immutable `RiskAssessment`, `classify_risk(delta)`, and the
  risk-limit predicate in `application/sql_emit/risk.py`.
- Classify deltas only. Table row-count/size estimates and other live catalog
  context are deferred until the domain/inspector can supply that information.
- Unknown `DeltaBase` subclasses fail closed as `BLOCKED` with a stable reason.
- The default generation limit is `DANGEROUS`: `SAFE`, `WARNING`, and
  `DANGEROUS` pass; `DESTRUCTIVE` does not. `BLOCKED` never passes, even when
  explicitly selected as the limit.
- Use explicit severity ordering, not lexical enum-value comparison.
- `RiskAssessment.reason` is deterministic, non-empty, and explains the
  classification; do not include SQL execution results or database-specific
  claims that the classifier cannot know.
- Revise ADR-0009 with the external-assessment contract and the default gate.

## API and behavior

`RiskLevel` is a `StrEnum` containing exactly `SAFE`, `WARNING`, `DANGEROUS`,
`DESTRUCTIVE`, and `BLOCKED`, ordered from least to most severe by an explicit
rank map. `RiskAssessment` is a frozen dataclass containing:

- `delta: DeltaBase` — original immutable delta being assessed;
- `level: RiskLevel`;
- `reason: str` — concise deterministic explanation.

`classify_risk(delta: DeltaBase) -> RiskAssessment` is pure: no database access,
mutation, logging, SQL parsing, or external dependencies. The gate API is
`passes_risk_limit(assessments: Iterable[RiskAssessment], *,
max_risk: RiskLevel = RiskLevel.DANGEROUS) -> bool`. It passes only when every
assessment is at or below the limit and none is `BLOCKED`. An empty assessment
set passes. A migration's aggregate risk is its highest delta assessment; an
empty set has no risky delta.

The five meanings are:

| Level | Meaning |
|---|---|
| `SAFE` | Additive or metadata-only change with no expected data rewrite or material lock. |
| `WARNING` | Usually data-preserving, but may need operator attention for locking, table work, or extension scripts. |
| `DANGEROUS` | May block for a material duration, require validation/rebuild, or change operational/integrity behavior. |
| `DESTRUCTIVE` | Removes data, schema objects, or an enforced integrity guarantee. Requires explicit opt-in above the default limit. |
| `BLOCKED` | No explicit risk policy exists or operation is unsupported. Never generate. |

## Initial delta mapping

These conservative static rules cover all current concrete delta variants.
Conditional cases take the highest applicable severity. Reasons state the
specific condition that selected the level.

| Delta | Level | Rule / rationale |
|---|---|---|
| `CreateSchema` | `SAFE` | Adds an empty namespace. |
| `DropSchema` | `DESTRUCTIVE` | Removes a namespace and its objects. |
| `CreateExtension` | `WARNING` | Extension installation may execute extension-provided scripts. |
| `DropExtension` | `DESTRUCTIVE` | Removes extension-provided objects and behavior. |
| `AlterExtension` | `DANGEROUS` if `new_version` is set; otherwise `WARNING` | Version updates may run extension migrations; schema relocation is operationally sensitive. |
| `CreateTable` | `SAFE`, except `WARNING` when `table.partition_of` is set | Empty ordinary table is additive; creating a partition child affects its parent. |
| `DropTable` | `DESTRUCTIVE` | Removes table and its data. |
| `RenameTable`, `RenameColumn` | `WARNING` | Requires a lock and can affect dependent application behavior. |
| `AlterTableAttrs` | `SAFE` for comment only; `WARNING` for tablespace; `DANGEROUS` for owner (TD-RISK-02), partition metadata, persistence and row security | Use highest severity among changed fields. Tablespace and partition changes can move/validate data or hold stronger locks. |
| `AddColumn` | `SAFE` only when nullable, with no default, identity, or generated expression; otherwise `WARNING` | Defaults, `NOT NULL`, identity, or stored generation can rewrite or validate existing rows. |
| `DropColumn` | `DESTRUCTIVE` | Removes column data. |
| `AlterColumnType` | `DANGEROUS` | Type conversion may rewrite the table and hold a long lock. |
| `SetColumnDefault` | `SAFE` | Changes the default for future writes; does not rewrite existing values. |
| `SetColumnNullability` | `SAFE` when setting nullable; `DANGEROUS` when setting `NOT NULL` | `NOT NULL` requires validation of existing rows and may block. |
| `CreateIndex` | `WARNING` | Delta has no execution-mode field, so classifier cannot prove `CONCURRENTLY` will be used. |
| `DropIndex` | `DANGEROUS`, or `DESTRUCTIVE` when the index is unique | Removes an access path; dropping a unique index also removes an enforced uniqueness guarantee. |
| `ReplaceIndex` | `DANGEROUS`, or `DESTRUCTIVE` when a unique old index becomes non-unique | Rebuild may block; removing uniqueness weakens an integrity guarantee. |
| `AddConstraint` | `DANGEROUS` | Validation/scans may be long or blocking and can fail on existing rows. |
| `DropConstraint` | `DESTRUCTIVE` | Removes an enforced integrity rule. |
| Any unrecognized delta subclass | `BLOCKED` | No policy exists; fail closed instead of assuming safety. |

These are policy classifications, not guarantees that PostgreSQL will execute
an operation without errors or downtime. In particular, `WARNING` for index
creation is intentional until execution-mode metadata can be part of the
assessment.

## Tests and acceptance

- Unit corpus covers every current concrete delta type and each conditional
  branch in the mapping.
- Tests verify all five levels, stable non-empty reasons, and preservation of
  the original delta in each assessment.
- Unknown delta subclasses produce `BLOCKED` and cannot pass the gate.
- Gate tests cover the default `DANGEROUS` limit, explicit `DESTRUCTIVE`
  opt-in, severity boundaries, and the invariant that `BLOCKED` never passes.
- Empty assessment collections do not fail the migration gate.
- ADR-0009 documents the external assessment, revised default, and fail-closed
  behavior.
- No changes to delta models, SQL emitters, CLI, table statistics, or external
  dependencies are required for P3-RISK-01.

## Out of scope

- Table-size/row-count estimates and data-dependent risk refinement.
- Inspecting generated SQL or transaction mode during classification.
- SQL emission, transaction splitting, migration writing, or applying SQL.
- CLI option parsing and destructive-change confirmation UI; later tasks
  consume the classifier and gate.
