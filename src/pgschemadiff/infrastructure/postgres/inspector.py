"""Concrete SchemaInspector implementation (task P1-INFRA-05).

``PgCatalogInspector`` queries ``pg_catalog`` via psycopg 3 async and
assembles a :class:`~pgschemadiff.domain.database.Database` snapshot.

Design decisions:
- Implements the :class:`~pgschemadiff.domain.ports.SchemaInspector` Protocol.
- Uses a single ``REPEATABLE READ`` transaction per ADR-0012 MVP.
- All six SQL files are loaded once at module import via
  ``importlib.resources`` (ADR-0004).
- Constraint column lists are parsed from ``pg_get_constraintdef`` output so
  that no extra round-trips are needed.
"""

from __future__ import annotations

import importlib.resources as importlib_resources
import re
from typing import TYPE_CHECKING, Any

import psycopg
import psycopg.rows

from pgschemadiff.domain.column import Column, GeneratedTiming, IdentitySpec
from pgschemadiff.domain.constraint import (
    CheckConstraint,
    ConstraintDeferrability,
    ExclusionConstraint,
    ExclusionElement,
    FKAction,
    FKMatch,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    UniqueConstraint,
)
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn, IndexMethod, NullsOrder, SortOrder
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import (
    PartitionInfo,
    PartitionOf,
    PartitionStrategy,
    Table,
)
from pgschemadiff.infrastructure.postgres.type_normalizer import normalize_type
from pgschemadiff.shared.errors import InspectionError

if TYPE_CHECKING:
    from pgschemadiff.infrastructure.postgres.pool import Pool

# Type alias for the concrete constraint union
_AnyConstraint = (
    PrimaryKeyConstraint
    | UniqueConstraint
    | CheckConstraint
    | ForeignKeyConstraint
    | ExclusionConstraint
)

# ---------------------------------------------------------------------------
# SQL loading — done once at module import
# ---------------------------------------------------------------------------

_CATALOG_PKG = "pgschemadiff.infrastructure.postgres.catalog"


def _load_sql(filename: str) -> str:
    """Load a SQL file from the catalog package via importlib.resources."""
    pkg = importlib_resources.files(_CATALOG_PKG)
    return (pkg / filename).read_text(encoding="utf-8")


_SQL_SCHEMAS: str = _load_sql("schemas.sql")
_SQL_TABLES: str = _load_sql("tables.sql")
_SQL_COLUMNS: str = _load_sql("columns.sql")
_SQL_INDEXES: str = _load_sql("indexes.sql")
_SQL_CONSTRAINTS: str = _load_sql("constraints.sql")
_SQL_EXTENSIONS: str = _load_sql("extensions.sql")

# ---------------------------------------------------------------------------
# Regex helpers for parsing pg_get_constraintdef output
# ---------------------------------------------------------------------------

# Matches e.g. "PRIMARY KEY (id, name)" or "UNIQUE (email)"
_RE_COL_LIST = re.compile(r"\(([^)]+)\)")

# Matches "FOREIGN KEY (local_col) REFERENCES schema.table (ref_col)"
_RE_FK = re.compile(
    r"FOREIGN KEY\s*\(([^)]+)\)\s*REFERENCES\s+(\S+)\s*\(([^)]+)\)",
    re.IGNORECASE,
)

# Match ON DELETE / ON UPDATE actions
_RE_ON_DELETE = re.compile(
    r"ON DELETE (CASCADE|RESTRICT|SET NULL|SET DEFAULT|NO ACTION)",
    re.IGNORECASE,
)
_RE_ON_UPDATE = re.compile(
    r"ON UPDATE (CASCADE|RESTRICT|SET NULL|SET DEFAULT|NO ACTION)",
    re.IGNORECASE,
)

# Match MATCH clause
_RE_MATCH = re.compile(r"\bMATCH (FULL|PARTIAL|SIMPLE)\b", re.IGNORECASE)

# Match EXCLUDE USING method (elements...) [WHERE ...]
_RE_EXCLUDE = re.compile(
    r"EXCLUDE USING (\w+)\s*\((.+?)\)(?:\s*WHERE\s*\((.+)\))?$",
    re.IGNORECASE | re.DOTALL,
)

# Match individual exclusion elements like "col WITH &&" or "(expr) WITH ="
_RE_EXCL_ELEM = re.compile(r"(\S+|\(.+?\))\s+WITH\s+(\S+)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _parse_columns_from_definition(definition: str) -> tuple[str, ...]:
    """Extract column names from a constraint definition like ``PRIMARY KEY (a, b)``."""
    m = _RE_COL_LIST.search(definition)
    if not m:
        return ()
    raw = m.group(1)
    return tuple(col.strip().strip('"') for col in raw.split(","))


def _map_fk_action(text: str) -> FKAction:
    """Map pg_get_constraintdef action text to an :class:`FKAction`."""
    _lookup: dict[str, FKAction] = {
        "CASCADE": FKAction.CASCADE,
        "RESTRICT": FKAction.RESTRICT,
        "SET NULL": FKAction.SET_NULL,
        "SET DEFAULT": FKAction.SET_DEFAULT,
        "NO ACTION": FKAction.NO_ACTION,
    }
    return _lookup.get(text.upper(), FKAction.NO_ACTION)


def _map_fk_match(text: str) -> FKMatch:
    """Map MATCH clause text to an :class:`FKMatch`."""
    _lookup: dict[str, FKMatch] = {
        "FULL": FKMatch.FULL,
        "PARTIAL": FKMatch.PARTIAL,
        "SIMPLE": FKMatch.SIMPLE,
    }
    return _lookup.get(text.upper(), FKMatch.SIMPLE)


def _map_deferrability(deferrable: bool, initially_deferred: bool) -> ConstraintDeferrability:
    """Derive :class:`ConstraintDeferrability` from the two pg_constraint flags."""
    if not deferrable:
        return ConstraintDeferrability.NOT_DEFERRABLE
    if initially_deferred:
        return ConstraintDeferrability.DEFERRABLE_INITIALLY_DEFERRED
    return ConstraintDeferrability.DEFERRABLE_INITIALLY_IMMEDIATE


def _map_partition_strategy(code: str) -> PartitionStrategy:
    """Map single-character partition strategy code to enum."""
    _lookup: dict[str, PartitionStrategy] = {
        "h": PartitionStrategy.HASH,
        "l": PartitionStrategy.LIST,
        "r": PartitionStrategy.RANGE,
    }
    return _lookup.get(code, PartitionStrategy.RANGE)


def _map_index_method(name: str) -> IndexMethod:
    """Map pg_am.amname to :class:`IndexMethod`."""
    try:
        return IndexMethod(name.lower())
    except ValueError:
        return IndexMethod.BTREE


def _split_top_level_commas(raw: str) -> list[str]:
    """Split *raw* at top-level commas (not inside parentheses)."""
    cols: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in raw:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            cols.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        cols.append("".join(current).strip())
    return cols


def _extract_paren_body(text: str) -> str | None:
    """Return the text between the first outermost pair of parentheses."""
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "(":
            if depth == 0:
                start = i + 1
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start:i]
    return None


def _parse_key_column_entry(col_str: str) -> IndexKeyColumn:
    """Parse one key column token into an :class:`IndexKeyColumn`."""
    parts = col_str.split()
    is_expr = col_str.strip().startswith("(")

    sort_order = SortOrder.ASC
    nulls_order: NullsOrder | None = None
    remaining = list(parts)

    # Extract NULLS FIRST / LAST from end (combined condition avoids SIM102)
    if (
        len(remaining) >= 2
        and remaining[-1].upper() in ("FIRST", "LAST")
        and remaining[-2].upper() == "NULLS"
    ):
        nulls_order = NullsOrder.FIRST if remaining[-1].upper() == "FIRST" else NullsOrder.LAST
        remaining = remaining[:-2]

    # Extract ASC / DESC
    if remaining and remaining[-1].upper() in ("ASC", "DESC"):
        sort_order = SortOrder.DESC if remaining[-1].upper() == "DESC" else SortOrder.ASC
        remaining = remaining[:-1]

    if is_expr:
        return IndexKeyColumn(
            expression=col_str.strip(),
            sort_order=sort_order,
            nulls_order=nulls_order,
        )

    col_name = remaining[0].strip('"') if remaining else "?"
    opclass: str | None = remaining[1] if len(remaining) > 1 else None
    return IndexKeyColumn(
        column_name=col_name,
        opclass=opclass,
        sort_order=sort_order,
        nulls_order=nulls_order,
    )


def _parse_index_key_columns(index_definition: str) -> tuple[IndexKeyColumn, ...]:
    """Extract key column entries from a full ``CREATE INDEX`` definition string.

    Best-effort MVP parser: finds the column list between the outermost
    parentheses of the index definition and splits on top-level commas.
    """
    raw_cols = _extract_paren_body(index_definition)
    if raw_cols is None:
        return (IndexKeyColumn(column_name="?"),)

    col_strings = _split_top_level_commas(raw_cols)
    key_columns = [_parse_key_column_entry(s) for s in col_strings if s.strip()]
    return tuple(key_columns) if key_columns else (IndexKeyColumn(column_name="?"),)


def _parse_exclusion_elements(body: str) -> tuple[ExclusionElement, ...]:
    """Parse exclusion elements from the body of an EXCLUDE clause."""
    elements = [
        ExclusionElement(column_or_expr=m.group(1).strip(), operator=m.group(2).strip())
        for m in _RE_EXCL_ELEM.finditer(body)
    ]
    if not elements:
        elements = [ExclusionElement(column_or_expr="?", operator="=")]
    return tuple(elements)


# ---------------------------------------------------------------------------
# Row-to-domain mappers
# ---------------------------------------------------------------------------


def _map_column(row: Any) -> Column:
    """Map a columns.sql result row to a :class:`Column` domain object."""
    is_identity: bool = bool(row.is_identity)
    is_generated: bool = bool(row.is_generated)

    identity: IdentitySpec | None = None
    if is_identity:
        identity = IdentitySpec(
            generated=(
                GeneratedTiming.ALWAYS
                if row.identity_generated == "ALWAYS"
                else GeneratedTiming.BY_DEFAULT
            )
        )

    generated_expression: str | None = row.generated_expr or None if is_generated else None
    default_expr: str | None = (
        row.default_expr or None if not is_identity and not is_generated else None
    )

    return Column(
        name=row.column_name,
        position=int(row.ordinal_position),
        data_type=normalize_type(row.data_type),
        nullable=bool(row.is_nullable),
        default_expr=default_expr,
        collation=row.collation or None,
        identity=identity,
        generated_expression=generated_expression,
    )


def _map_index(row: Any) -> Index:
    """Map an indexes.sql result row to an :class:`Index` domain object."""
    schema_name: str = row.schema_name
    table_name: str = row.table_name
    index_name: str = row.index_name

    return Index(
        ref=ObjectRef(
            kind=ObjectKind.INDEX,
            qname=QualifiedName(namespace=schema_name, name=index_name),
        ),
        table_ref=ObjectRef(
            kind=ObjectKind.TABLE,
            qname=QualifiedName(namespace=schema_name, name=table_name),
        ),
        method=_map_index_method(row.index_method),
        key_columns=_parse_index_key_columns(row.index_definition),
        unique=bool(row.is_unique),
        predicate=row.predicate or None,
    )


def _map_pk_constraint(
    name: str,
    definition: str,
    deferrability: ConstraintDeferrability,
) -> PrimaryKeyConstraint:
    cols = _parse_columns_from_definition(definition) or ("?",)
    return PrimaryKeyConstraint(name=name, columns=cols, deferrability=deferrability)


def _map_unique_constraint(
    name: str,
    definition: str,
    deferrability: ConstraintDeferrability,
) -> UniqueConstraint:
    cols = _parse_columns_from_definition(definition) or ("?",)
    nulls_not_distinct = "NULLS NOT DISTINCT" in definition.upper()
    return UniqueConstraint(
        name=name,
        columns=cols,
        nulls_not_distinct=nulls_not_distinct,
        deferrability=deferrability,
    )


def _map_check_constraint(
    name: str,
    definition: str,
    deferrability: ConstraintDeferrability,
) -> CheckConstraint:
    m = re.search(r"CHECK\s*\((.+)\)$", definition, re.IGNORECASE | re.DOTALL)
    expression = m.group(1) if m else definition
    no_inherit = "NO INHERIT" in definition.upper()
    return CheckConstraint(
        name=name,
        expression=expression,
        no_inherit=no_inherit,
        deferrability=deferrability,
    )


def _resolve_fk_target(row: Any, ref_target: str) -> tuple[str, str]:
    """Return ``(ref_namespace, ref_table_name)`` for a foreign-key row."""
    if row.ref_schema and row.ref_table:
        return str(row.ref_schema), str(row.ref_table)
    if "." in ref_target:
        parts = ref_target.split(".", 1)
        return parts[0].strip('"'), parts[1].strip('"')
    return "public", ref_target.strip('"') or "?"


def _map_fk_constraint(
    name: str,
    definition: str,
    deferrability: ConstraintDeferrability,
    row: Any,
) -> ForeignKeyConstraint:
    fk_m = _RE_FK.search(definition)
    if fk_m:
        local_cols = tuple(c.strip().strip('"') for c in fk_m.group(1).split(","))
        ref_target = fk_m.group(2).strip()
        ref_cols = tuple(c.strip().strip('"') for c in fk_m.group(3).split(","))
    else:
        local_cols = ("?",)
        ref_cols = ("?",)
        ref_target = ""

    ref_namespace, ref_table_name = _resolve_fk_target(row, ref_target)

    del_m = _RE_ON_DELETE.search(definition)
    upd_m = _RE_ON_UPDATE.search(definition)
    match_m = _RE_MATCH.search(definition)

    return ForeignKeyConstraint(
        name=name,
        columns=local_cols,
        ref_namespace=ref_namespace,
        ref_table=ref_table_name,
        ref_columns=ref_cols,
        on_delete=_map_fk_action(del_m.group(1)) if del_m else FKAction.NO_ACTION,
        on_update=_map_fk_action(upd_m.group(1)) if upd_m else FKAction.NO_ACTION,
        match_type=_map_fk_match(match_m.group(1)) if match_m else FKMatch.SIMPLE,
        deferrability=deferrability,
    )


def _map_exclusion_constraint(
    name: str,
    definition: str,
    deferrability: ConstraintDeferrability,
) -> ExclusionConstraint:
    excl_m = _RE_EXCLUDE.search(definition)
    if excl_m:
        index_method = excl_m.group(1)
        elements = _parse_exclusion_elements(excl_m.group(2))
        predicate_str: str | None = excl_m.group(3) or None
    else:
        index_method = "gist"
        elements = (ExclusionElement(column_or_expr="?", operator="="),)
        predicate_str = None

    return ExclusionConstraint(
        name=name,
        index_method=index_method,
        elements=elements,
        predicate=predicate_str,
        deferrability=deferrability,
    )


def _map_constraint(row: Any) -> _AnyConstraint:
    """Map a constraints.sql result row to a concrete constraint domain object."""
    constraint_type: str = row.constraint_type
    name: str = row.constraint_name
    definition: str = row.definition
    deferrability = _map_deferrability(bool(row.deferrable), bool(row.initially_deferred))

    if constraint_type == "p":
        return _map_pk_constraint(name, definition, deferrability)
    if constraint_type == "u":
        return _map_unique_constraint(name, definition, deferrability)
    if constraint_type == "c":
        return _map_check_constraint(name, definition, deferrability)
    if constraint_type == "f":
        return _map_fk_constraint(name, definition, deferrability, row)
    if constraint_type == "x":
        return _map_exclusion_constraint(name, definition, deferrability)
    raise InspectionError(f"Unknown constraint type: {constraint_type!r}")


def _safe_map_constraints(
    rows: list[Any],
    col_names: frozenset[str],
) -> list[_AnyConstraint]:
    """Map constraint rows, skipping any that fail validation."""
    result: list[_AnyConstraint] = []
    for crow in rows:
        try:
            ct = _map_constraint(crow)
            # Skip PK/Unique/FK whose columns don't exist (partition inheritance)
            if isinstance(
                ct, (PrimaryKeyConstraint, UniqueConstraint, ForeignKeyConstraint)
            ) and not all(c in col_names for c in ct.columns):
                continue
            result.append(ct)
        except Exception:
            continue
    return result


def _build_partition_info(row: Any) -> PartitionInfo | None:
    """Build a :class:`PartitionInfo` from a tables row, or ``None``."""
    if row.partition_strategy is not None and row.partition_expr is not None:
        return PartitionInfo(
            strategy=_map_partition_strategy(row.partition_strategy),
            partition_key=row.partition_expr,
        )
    return None


def _build_partition_of(row: Any) -> PartitionOf | None:
    """Build a :class:`PartitionOf` from a tables row, or ``None``."""
    if row.partition_of_schema is not None and row.partition_of_table is not None:
        return PartitionOf(
            parent_namespace=row.partition_of_schema,
            parent_name=row.partition_of_table,
            partition_bound=row.partition_bound or None,
        )
    return None


# ---------------------------------------------------------------------------
# Main inspector class
# ---------------------------------------------------------------------------


class PgCatalogInspector:
    """Concrete SchemaInspector: reads pg_catalog via psycopg3 async.

    Implements the :class:`~pgschemadiff.domain.ports.SchemaInspector` port.
    Uses a single ``REPEATABLE READ`` transaction per ADR-0012 MVP.
    SQL files loaded via ``importlib.resources`` from the ``catalog/`` package.

    Parameters
    ----------
    pool:
        The :class:`~pgschemadiff.infrastructure.postgres.pool.Pool` instance
        (must already be open, i.e. inside ``async with Pool(...) as pool``).
    schemas:
        Optional list of schema names to inspect.  ``None`` means all
        user-defined schemas.
    """

    def __init__(self, pool: Pool, *, schemas: list[str] | None = None) -> None:
        self._pool = pool
        self._schemas: list[str] | None = schemas

    async def inspect(self) -> Database:
        """Execute catalog queries and assemble a ``Database`` snapshot.

        Uses ``REPEATABLE READ`` isolation for consistency (ADR-0012 MVP).
        Returns a fully populated :class:`~pgschemadiff.domain.database.Database`
        domain object.

        Raises
        ------
        pgschemadiff.shared.errors.InspectionError
            If a catalog query fails or the rows cannot be mapped to domain
            objects.
        """
        try:
            return await self._run_inspect()
        except InspectionError:
            raise
        except Exception as exc:
            raise InspectionError(f"Catalog inspection failed: {exc}") from exc

    async def _run_inspect(self) -> Database:
        async with self._pool.acquire() as conn:
            # Use REPEATABLE READ for snapshot consistency (ADR-0012)
            await conn.set_autocommit(False)
            await conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ")
            try:
                async with conn.cursor(row_factory=psycopg.rows.namedtuple_row) as cur:
                    await cur.execute(_SQL_SCHEMAS)
                    schemas_rows = await cur.fetchall()

                    await cur.execute(_SQL_TABLES)
                    tables_rows = await cur.fetchall()

                    await cur.execute(_SQL_COLUMNS)
                    columns_rows = await cur.fetchall()

                    await cur.execute(_SQL_INDEXES)
                    indexes_rows = await cur.fetchall()

                    await cur.execute(_SQL_CONSTRAINTS)
                    constraints_rows = await cur.fetchall()

                    await cur.execute(_SQL_EXTENSIONS)
                    extensions_rows = await cur.fetchall()
            finally:
                await conn.execute("ROLLBACK")

        return self._assemble(
            schemas_rows=schemas_rows,
            tables_rows=tables_rows,
            columns_rows=columns_rows,
            indexes_rows=indexes_rows,
            constraints_rows=constraints_rows,
            extensions_rows=extensions_rows,
        )

    def _assemble(
        self,
        *,
        schemas_rows: list[Any],
        tables_rows: list[Any],
        columns_rows: list[Any],
        indexes_rows: list[Any],
        constraints_rows: list[Any],
        extensions_rows: list[Any],
    ) -> Database:
        """Assemble domain objects from raw catalog rows."""
        extensions = self._build_extensions(extensions_rows)

        allowed: set[str] | None = set(self._schemas) if self._schemas is not None else None
        schema_names = [
            row.schema_name for row in schemas_rows if allowed is None or row.schema_name in allowed
        ]

        cols_by_table = self._group_columns(columns_rows, allowed)
        idxs_by_table = self._group_indexes(indexes_rows, allowed)
        cons_by_table = self._group_constraints(constraints_rows, allowed)

        tables_by_schema, idxs_by_schema = self._build_tables(
            tables_rows, schema_names, cols_by_table, idxs_by_table, cons_by_table
        )

        return Database(
            name="inspected",
            schemas=tuple(self._build_schemas(schema_names, tables_by_schema, idxs_by_schema)),
            extensions=tuple(extensions),
        )

    # ------------------------------------------------------------------
    # Grouping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _group_columns(
        rows: list[Any],
        allowed: set[str] | None,
    ) -> dict[tuple[str, str], list[Column]]:
        result: dict[tuple[str, str], list[Column]] = {}
        for row in rows:
            if allowed is not None and row.schema_name not in allowed:
                continue
            result.setdefault((row.schema_name, row.table_name), []).append(_map_column(row))
        return result

    @staticmethod
    def _group_indexes(
        rows: list[Any],
        allowed: set[str] | None,
    ) -> dict[tuple[str, str], list[Index]]:
        result: dict[tuple[str, str], list[Index]] = {}
        for row in rows:
            if allowed is not None and row.schema_name not in allowed:
                continue
            result.setdefault((row.schema_name, row.table_name), []).append(_map_index(row))
        return result

    @staticmethod
    def _group_constraints(
        rows: list[Any],
        allowed: set[str] | None,
    ) -> dict[tuple[str, str], list[Any]]:
        result: dict[tuple[str, str], list[Any]] = {}
        for row in rows:
            if allowed is not None and row.schema_name not in allowed:
                continue
            result.setdefault((row.schema_name, row.table_name), []).append(row)
        return result

    # ------------------------------------------------------------------
    # Table builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_tables(
        tables_rows: list[Any],
        schema_names: list[str],
        cols_by_table: dict[tuple[str, str], list[Column]],
        idxs_by_table: dict[tuple[str, str], list[Index]],
        cons_by_table: dict[tuple[str, str], list[Any]],
    ) -> tuple[dict[str, list[Table]], dict[str, list[Index]]]:
        tables_by_schema: dict[str, list[Table]] = {n: [] for n in schema_names}
        idxs_by_schema: dict[str, list[Index]] = {n: [] for n in schema_names}

        for row in tables_rows:
            schema_name: str = row.schema_name
            if schema_name not in tables_by_schema:
                continue

            table_name: str = row.table_name
            key = (schema_name, table_name)

            cols = sorted(cols_by_table.get(key, []), key=lambda c: c.position)
            col_names: frozenset[str] = frozenset(c.name for c in cols)

            tables_by_schema[schema_name].append(
                Table(
                    ref=ObjectRef(
                        kind=ObjectKind.TABLE,
                        qname=QualifiedName(namespace=schema_name, name=table_name),
                    ),
                    columns=tuple(cols),
                    constraints=tuple(_safe_map_constraints(cons_by_table.get(key, []), col_names)),
                    partition_info=_build_partition_info(row),
                    partition_of=_build_partition_of(row),
                )
            )
            idxs_by_schema[schema_name].extend(idxs_by_table.get(key, []))

        return tables_by_schema, idxs_by_schema

    # ------------------------------------------------------------------
    # Schema builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_schemas(
        schema_names: list[str],
        tables_by_schema: dict[str, list[Table]],
        idxs_by_schema: dict[str, list[Index]],
    ) -> list[Schema]:
        result: list[Schema] = []
        for name in schema_names:
            result.append(
                Schema(
                    ref=ObjectRef(
                        kind=ObjectKind.SCHEMA,
                        qname=QualifiedName(namespace=name, name=name),
                    ),
                    tables=tuple(tables_by_schema.get(name, [])),
                    indexes=tuple(idxs_by_schema.get(name, [])),
                )
            )
        return result

    # ------------------------------------------------------------------
    # Extension builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_extensions(rows: list[Any]) -> list[Extension]:
        """Map extension rows to :class:`Extension` domain objects."""
        result: list[Extension] = []
        for row in rows:
            result.append(
                Extension(
                    ref=ObjectRef(
                        kind=ObjectKind.EXTENSION,
                        qname=QualifiedName(namespace="public", name=row.extension_name),
                    ),
                    version=row.installed_version or "0",
                )
            )
        return result
