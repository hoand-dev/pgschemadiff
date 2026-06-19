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
from pgschemadiff.shared.errors import InspectionError

if TYPE_CHECKING:
    from pgschemadiff.infrastructure.postgres.pool import Pool

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
# or "FOREIGN KEY (a, b) REFERENCES schema.table (c, d)"
_RE_FK = re.compile(
    r"FOREIGN KEY\s*\(([^)]+)\)\s*REFERENCES\s+(\S+)\s*\(([^)]+)\)",
    re.IGNORECASE,
)

# Match ON DELETE / ON UPDATE actions
_RE_ON_DELETE = re.compile(
    r"ON DELETE (CASCADE|RESTRICT|SET NULL|SET DEFAULT|NO ACTION)", re.IGNORECASE
)
_RE_ON_UPDATE = re.compile(
    r"ON UPDATE (CASCADE|RESTRICT|SET NULL|SET DEFAULT|NO ACTION)", re.IGNORECASE
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
    upper = text.upper()
    if upper == "CASCADE":
        return FKAction.CASCADE
    if upper == "RESTRICT":
        return FKAction.RESTRICT
    if upper == "SET NULL":
        return FKAction.SET_NULL
    if upper == "SET DEFAULT":
        return FKAction.SET_DEFAULT
    return FKAction.NO_ACTION


def _map_fk_match(text: str) -> FKMatch:
    """Map MATCH clause text to an :class:`FKMatch`."""
    upper = text.upper()
    if upper == "FULL":
        return FKMatch.FULL
    if upper == "PARTIAL":
        return FKMatch.PARTIAL
    return FKMatch.SIMPLE


def _map_deferrability(deferrable: bool, initially_deferred: bool) -> ConstraintDeferrability:
    """Derive :class:`ConstraintDeferrability` from the two pg_constraint flags."""
    if not deferrable:
        return ConstraintDeferrability.NOT_DEFERRABLE
    if initially_deferred:
        return ConstraintDeferrability.DEFERRABLE_INITIALLY_DEFERRED
    return ConstraintDeferrability.DEFERRABLE_INITIALLY_IMMEDIATE


def _map_partition_strategy(code: str) -> PartitionStrategy:
    """Map single-character partition strategy code to enum."""
    if code == "h":
        return PartitionStrategy.HASH
    if code == "l":
        return PartitionStrategy.LIST
    return PartitionStrategy.RANGE


def _map_index_method(name: str) -> IndexMethod:
    """Map pg_am.amname to :class:`IndexMethod`."""
    try:
        return IndexMethod(name.lower())
    except ValueError:
        return IndexMethod.BTREE


def _parse_index_key_columns(index_definition: str) -> tuple[IndexKeyColumn, ...]:  # noqa: PLR0912
    """Extract key column entries from a full ``CREATE INDEX`` definition string.

    This is a best-effort MVP parser.  It finds the column list between the
    outermost parentheses of the index definition and splits on commas.  For
    each entry it tries to detect expression columns (those wrapped in parens)
    versus plain column names.  Sort order and ``NULLS`` clauses are parsed if
    present; opclass names are captured as a trailing token before any
    ``ASC``/``DESC`` or ``NULLS`` keyword.
    """
    # Find outermost parens - skip schema.table part
    depth = 0
    start = -1
    for i, ch in enumerate(index_definition):
        if ch == "(":
            if depth == 0:
                start = i + 1
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                raw_cols = index_definition[start:i]
                break
    else:
        # No parens found — return a minimal key column
        return (IndexKeyColumn(column_name="?"),)

    # Split at top-level commas
    cols: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in raw_cols:
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

    key_columns: list[IndexKeyColumn] = []
    for col_str in cols:
        parts = col_str.split()
        if not parts:
            continue

        # Check if first part is an expression (starts with '(')
        is_expr = col_str.strip().startswith("(")

        sort_order = SortOrder.ASC
        nulls_order: NullsOrder | None = None
        opclass: str | None = None

        # Parse trailing sort/nulls/opclass tokens
        # Format: col_or_expr [opclass] [ASC|DESC] [NULLS FIRST|LAST]
        remaining_parts = list(parts)

        # Extract NULLS FIRST / LAST from end
        if (
            len(remaining_parts) >= 2
            and remaining_parts[-1].upper() in ("FIRST", "LAST")
            and remaining_parts[-2].upper() == "NULLS"
        ):
            nulls_order = (
                NullsOrder.FIRST if remaining_parts[-1].upper() == "FIRST" else NullsOrder.LAST
            )
            remaining_parts = remaining_parts[:-2]

        # Extract ASC / DESC
        if remaining_parts and remaining_parts[-1].upper() in ("ASC", "DESC"):
            sort_order = SortOrder.DESC if remaining_parts[-1].upper() == "DESC" else SortOrder.ASC
            remaining_parts = remaining_parts[:-1]

        if is_expr:
            # Re-assemble expression (everything before trailing sort tokens)
            key_columns.append(
                IndexKeyColumn(
                    expression=col_str.strip(),
                    sort_order=sort_order,
                    nulls_order=nulls_order,
                )
            )
        else:
            # First token is the column name
            col_name = remaining_parts[0].strip('"') if remaining_parts else "?"
            # Remaining tokens after column name are opclass
            if len(remaining_parts) > 1:
                opclass = remaining_parts[1]
            key_columns.append(
                IndexKeyColumn(
                    column_name=col_name,
                    opclass=opclass,
                    sort_order=sort_order,
                    nulls_order=nulls_order,
                )
            )

    return tuple(key_columns) if key_columns else (IndexKeyColumn(column_name="?"),)


def _parse_exclusion_elements(body: str) -> tuple[ExclusionElement, ...]:
    """Parse exclusion elements from the body of an EXCLUDE clause."""
    elements: list[ExclusionElement] = []
    for m in _RE_EXCL_ELEM.finditer(body):
        col_or_expr = m.group(1).strip()
        operator = m.group(2).strip()
        elements.append(ExclusionElement(column_or_expr=col_or_expr, operator=operator))
    if not elements:
        # Fallback: create a minimal element
        elements.append(ExclusionElement(column_or_expr="?", operator="="))
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

    generated_expression: str | None = None
    if is_generated:
        generated_expression = row.generated_expr or None

    default_expr: str | None = None
    if not is_identity and not is_generated:
        default_expr = row.default_expr or None

    return Column(
        name=row.column_name,
        position=int(row.ordinal_position),
        data_type=row.data_type,
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
    index_definition: str = row.index_definition

    index_ref = ObjectRef(
        kind=ObjectKind.INDEX,
        qname=QualifiedName(namespace=schema_name, name=index_name),
    )
    table_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace=schema_name, name=table_name),
    )

    key_columns = _parse_index_key_columns(index_definition)
    method = _map_index_method(row.index_method)
    predicate: str | None = row.predicate or None

    return Index(
        ref=index_ref,
        table_ref=table_ref,
        method=method,
        key_columns=key_columns,
        unique=bool(row.is_unique),
        predicate=predicate,
    )


Constraint = (
    PrimaryKeyConstraint
    | UniqueConstraint
    | CheckConstraint
    | ForeignKeyConstraint
    | ExclusionConstraint
)


def _map_constraint(row: Any) -> Constraint:  # noqa: PLR0912, PLR0915
    """Map a constraints.sql result row to a concrete constraint domain object."""
    constraint_type: str = row.constraint_type
    name: str = row.constraint_name
    definition: str = row.definition
    deferrable: bool = bool(row.deferrable)
    initially_deferred: bool = bool(row.initially_deferred)
    deferrability = _map_deferrability(deferrable, initially_deferred)

    if constraint_type == "p":
        cols = _parse_columns_from_definition(definition)
        if not cols:
            cols = ("?",)
        return PrimaryKeyConstraint(
            name=name,
            columns=cols,
            deferrability=deferrability,
        )

    if constraint_type == "u":
        cols = _parse_columns_from_definition(definition)
        if not cols:
            cols = ("?",)
        nulls_not_distinct = "NULLS NOT DISTINCT" in definition.upper()
        return UniqueConstraint(
            name=name,
            columns=cols,
            nulls_not_distinct=nulls_not_distinct,
            deferrability=deferrability,
        )

    if constraint_type == "c":
        # CheckConstraint: extract the CHECK (...) expression
        m = re.search(r"CHECK\s*\((.+)\)$", definition, re.IGNORECASE | re.DOTALL)
        expression = m.group(1) if m else definition
        no_inherit = "NO INHERIT" in definition.upper()
        return CheckConstraint(
            name=name,
            expression=expression,
            no_inherit=no_inherit,
            deferrability=deferrability,
        )

    if constraint_type == "f":
        fk_m = _RE_FK.search(definition)
        if fk_m:
            local_cols = tuple(c.strip().strip('"') for c in fk_m.group(1).split(","))
            ref_target = fk_m.group(2).strip()
            ref_cols = tuple(c.strip().strip('"') for c in fk_m.group(3).split(","))
        else:
            local_cols = ("?",)
            ref_cols = ("?",)
            ref_target = ""

        # Determine ref_namespace and ref_table
        ref_namespace: str
        ref_table_name: str
        if row.ref_schema and row.ref_table:
            ref_namespace = row.ref_schema
            ref_table_name = row.ref_table
        elif "." in ref_target:
            parts = ref_target.split(".", 1)
            ref_namespace = parts[0].strip('"')
            ref_table_name = parts[1].strip('"')
        else:
            ref_namespace = "public"
            ref_table_name = ref_target.strip('"') or "?"

        # Parse ON DELETE / ON UPDATE
        del_m = _RE_ON_DELETE.search(definition)
        upd_m = _RE_ON_UPDATE.search(definition)
        on_delete = _map_fk_action(del_m.group(1)) if del_m else FKAction.NO_ACTION
        on_update = _map_fk_action(upd_m.group(1)) if upd_m else FKAction.NO_ACTION

        match_m = _RE_MATCH.search(definition)
        match_type = _map_fk_match(match_m.group(1)) if match_m else FKMatch.SIMPLE

        return ForeignKeyConstraint(
            name=name,
            columns=local_cols,
            ref_namespace=ref_namespace,
            ref_table=ref_table_name,
            ref_columns=ref_cols,
            on_delete=on_delete,
            on_update=on_update,
            match_type=match_type,
            deferrability=deferrability,
        )

    if constraint_type == "x":
        excl_m = _RE_EXCLUDE.search(definition)
        if excl_m:
            index_method = excl_m.group(1)
            elements_str = excl_m.group(2)
            predicate_str: str | None = excl_m.group(3) or None
            elements = _parse_exclusion_elements(elements_str)
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

    raise InspectionError(f"Unknown constraint type: {constraint_type!r}")


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
                # Use a cursor with namedtuple rows for attribute-style access
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

    def _assemble(  # noqa: PLR0912, PLR0915
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
        # --- Extensions ---
        extensions = self._build_extensions(extensions_rows)

        # --- Filter schemas ---
        allowed_schemas: set[str] | None = set(self._schemas) if self._schemas is not None else None
        schema_names: list[str] = [
            row.schema_name
            for row in schemas_rows
            if allowed_schemas is None or row.schema_name in allowed_schemas
        ]

        # --- Tables: first pass — shell Table objects keyed by (schema, table) ---
        # Build column/index/constraint lists grouped by table key
        cols_by_table: dict[tuple[str, str], list[Column]] = {}
        for row in columns_rows:
            key = (row.schema_name, row.table_name)
            if allowed_schemas is not None and row.schema_name not in allowed_schemas:
                continue
            cols_by_table.setdefault(key, []).append(_map_column(row))

        indexes_by_table: dict[tuple[str, str], list[Index]] = {}
        for row in indexes_rows:
            key = (row.schema_name, row.table_name)
            if allowed_schemas is not None and row.schema_name not in allowed_schemas:
                continue
            indexes_by_table.setdefault(key, []).append(_map_index(row))

        constraints_by_table: dict[tuple[str, str], list[Any]] = {}
        for row in constraints_rows:
            key = (row.schema_name, row.table_name)
            if allowed_schemas is not None and row.schema_name not in allowed_schemas:
                continue
            constraints_by_table.setdefault(key, []).append(row)

        # --- Build Table objects ---
        # Collect all tables whose schema passes the filter
        tables_by_schema: dict[str, list[Table]] = {name: [] for name in schema_names}
        indexes_by_schema: dict[str, list[Index]] = {name: [] for name in schema_names}

        for row in tables_rows:
            schema_name: str = row.schema_name
            if schema_name not in tables_by_schema:
                continue
            table_name: str = row.table_name

            table_key = (schema_name, table_name)

            # Sort columns by position
            cols: list[Column] = sorted(cols_by_table.get(table_key, []), key=lambda c: c.position)

            # Map constraint rows to domain objects
            constraint_objects: list[Any] = []
            col_names: frozenset[str] = frozenset(c.name for c in cols)
            for crow in constraints_by_table.get(table_key, []):
                try:
                    ct = _map_constraint(crow)
                    # Validate FK/PK/Unique columns exist before adding
                    if isinstance(
                        ct, (PrimaryKeyConstraint, UniqueConstraint, ForeignKeyConstraint)
                    ):
                        valid = all(c in col_names for c in ct.columns)
                        if not valid:
                            # Skip constraints referencing unknown columns
                            # (can happen with partition inheritance)
                            continue
                    constraint_objects.append(ct)
                except (InspectionError, Exception):
                    # Skip malformed constraints in MVP
                    continue

            # Build partition info
            partition_info: PartitionInfo | None = None
            if row.partition_strategy is not None and row.partition_expr is not None:
                strategy = _map_partition_strategy(row.partition_strategy)
                partition_info = PartitionInfo(
                    strategy=strategy,
                    partition_key=row.partition_expr,
                )

            partition_of: PartitionOf | None = None
            if row.partition_of_schema is not None and row.partition_of_table is not None:
                partition_of = PartitionOf(
                    parent_namespace=row.partition_of_schema,
                    parent_name=row.partition_of_table,
                    partition_bound=row.partition_bound or None,
                )

            table_ref = ObjectRef(
                kind=ObjectKind.TABLE,
                qname=QualifiedName(namespace=schema_name, name=table_name),
            )
            table = Table(
                ref=table_ref,
                columns=tuple(cols),
                constraints=tuple(constraint_objects),
                partition_info=partition_info,
                partition_of=partition_of,
            )
            tables_by_schema[schema_name].append(table)

            # Collect indexes for the schema-level index list
            indexes_by_schema[schema_name].extend(indexes_by_table.get(table_key, []))

        # --- Build Schema objects ---
        schema_objects: list[Schema] = []
        for name in schema_names:
            schema_ref = ObjectRef(
                kind=ObjectKind.SCHEMA,
                qname=QualifiedName(namespace=name, name=name),
            )
            schema = Schema(
                ref=schema_ref,
                tables=tuple(tables_by_schema.get(name, [])),
                indexes=tuple(indexes_by_schema.get(name, [])),
            )
            schema_objects.append(schema)

        return Database(
            name="inspected",
            schemas=tuple(schema_objects),
            extensions=tuple(extensions),
        )

    def _build_extensions(self, rows: list[Any]) -> list[Extension]:
        """Map extension rows to :class:`Extension` domain objects."""
        result: list[Extension] = []
        for row in rows:
            ext_ref = ObjectRef(
                kind=ObjectKind.EXTENSION,
                qname=QualifiedName(namespace="public", name=row.extension_name),
            )
            result.append(
                Extension(
                    ref=ext_ref,
                    version=row.installed_version or "0",
                )
            )
        return result
