"""Concrete SchemaInspector implementation (task P1-INFRA-05).

``PgCatalogInspector`` queries ``pg_catalog`` via psycopg 3 async and
assembles a :class:`~pgschemadiff.domain.database.Database` snapshot.

Design decisions:
- Implements the :class:`~pgschemadiff.domain.ports.SchemaInspector` Protocol.
- Uses a single ``REPEATABLE READ`` transaction per ADR-0012 MVP.
- Catalog SQL files are loaded once at module import via
  ``importlib.resources`` (ADR-0004).
- Constraint column lists are parsed from ``pg_get_constraintdef`` output so
  that no extra round-trips are needed.
"""

from __future__ import annotations

import importlib.resources as importlib_resources
import re
from typing import TYPE_CHECKING, Any, Literal

import psycopg
import psycopg.rows

from pgschemadiff.domain.column import Column, GeneratedTiming, IdentitySpec
from pgschemadiff.domain.composite_type import CompositeAttribute, CompositeType
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
from pgschemadiff.domain.domain_type import DomainCheck, DomainType
from pgschemadiff.domain.enum_type import EnumType
from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.function import Function, FunctionArgument
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn, IndexMethod, NullsOrder, SortOrder
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.sequence import Sequence
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
_SQL_ENUMS: str = _load_sql("enums.sql")
_SQL_COMPOSITE_TYPES: str = _load_sql("composite_types.sql")
_SQL_DOMAIN_TYPES: str = _load_sql("domain_types.sql")
_SQL_TYPE_PREREQUISITES: str = _load_sql("type_prerequisites.sql")
_SQL_SEQUENCES: str = _load_sql("sequences.sql")
_SQL_SEQUENCE_PREREQUISITES: str = _load_sql("sequence_prerequisites.sql")
_SQL_ROUTINES: str = _load_sql("routines.sql")

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
    except ValueError as exc:
        raise InspectionError(f"Unsupported PostgreSQL index method: {name!r}") from exc


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


def _map_column(
    row: Any,
    *,
    sequence_prerequisites: tuple[ObjectRef, ...] = (),
) -> Column:
    """Map a columns.sql result row to a :class:`Column` domain object."""
    is_identity: bool = bool(row.is_identity)
    is_generated: bool = bool(row.is_generated)
    is_virtual_generated: bool = bool(row.is_virtual_generated)

    identity: IdentitySpec | None = None
    if is_identity:
        identity = IdentitySpec(
            generated=(
                GeneratedTiming.ALWAYS
                if row.identity_generated == "ALWAYS"
                else GeneratedTiming.BY_DEFAULT
            )
        )

    generated_expression: str | None = (
        row.generated_expr or None if is_generated or is_virtual_generated else None
    )
    generated_kind: Literal["stored", "virtual"] | None = None
    if is_generated:
        generated_kind = "stored"
    elif is_virtual_generated:
        generated_kind = "virtual"
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
        generated_kind=generated_kind,
        sequence_prerequisites=sequence_prerequisites,
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
        include_columns=tuple(row.include_columns or ()),
        unique=bool(row.is_unique),
        predicate=row.predicate or None,
        definition=row.index_definition,
        constraint_name=row.constraint_name,
        partitioned=bool(row.partitioned),
        attached_to_parent=bool(row.attached_to_parent),
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

    constraint: _AnyConstraint
    if constraint_type == "p":
        constraint = _map_pk_constraint(name, definition, deferrability)
    elif constraint_type == "u":
        constraint = _map_unique_constraint(name, definition, deferrability)
    elif constraint_type == "c":
        constraint = _map_check_constraint(name, definition, deferrability)
    elif constraint_type == "f":
        constraint = _map_fk_constraint(name, definition, deferrability, row)
    elif constraint_type == "x":
        constraint = _map_exclusion_constraint(name, definition, deferrability)
    else:
        raise InspectionError(f"Unknown constraint type: {constraint_type!r}")

    return constraint.model_copy(
        update={"definition": definition, "inherited": bool(row.inherited)}
    )


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
            # Deparsers qualify user objects outside pg_catalog. LOCAL keeps pooled
            # sessions clean.
            await conn.execute("SET LOCAL search_path = pg_catalog")
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

                    await cur.execute(_SQL_ENUMS)
                    enums_rows = await cur.fetchall()

                    await cur.execute(_SQL_COMPOSITE_TYPES)
                    composite_types_rows = await cur.fetchall()

                    await cur.execute(_SQL_DOMAIN_TYPES)
                    domain_types_rows = await cur.fetchall()

                    await cur.execute(_SQL_TYPE_PREREQUISITES)
                    type_prerequisites_rows = await cur.fetchall()

                    await cur.execute(_SQL_SEQUENCES)
                    sequences_rows = await cur.fetchall()

                    await cur.execute(_SQL_SEQUENCE_PREREQUISITES)
                    sequence_prerequisites_rows = await cur.fetchall()

                    await cur.execute(_SQL_ROUTINES)
                    routines_rows = await cur.fetchall()
            finally:
                await conn.execute("ROLLBACK")

        return self._assemble(
            schemas_rows=schemas_rows,
            tables_rows=tables_rows,
            columns_rows=columns_rows,
            indexes_rows=indexes_rows,
            constraints_rows=constraints_rows,
            extensions_rows=extensions_rows,
            enums_rows=enums_rows,
            composite_types_rows=composite_types_rows,
            domain_types_rows=domain_types_rows,
            type_prerequisites_rows=type_prerequisites_rows,
            sequences_rows=sequences_rows,
            sequence_prerequisites_rows=sequence_prerequisites_rows,
            routines_rows=routines_rows,
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
        enums_rows: list[Any],
        composite_types_rows: list[Any],
        domain_types_rows: list[Any],
        type_prerequisites_rows: list[Any],
        sequences_rows: list[Any] | None = None,
        sequence_prerequisites_rows: list[Any] | None = None,
        routines_rows: list[Any] | None = None,
    ) -> Database:
        """Assemble domain objects from raw catalog rows."""
        extensions = self._build_extensions(extensions_rows)

        allowed: set[str] | None = set(self._schemas) if self._schemas is not None else None
        schemas_by_name = {row.schema_name: row for row in schemas_rows}
        schema_names = [
            row.schema_name for row in schemas_rows if allowed is None or row.schema_name in allowed
        ]

        sequence_prerequisites_by_column = self._group_sequence_prerequisites(
            sequence_prerequisites_rows or [], allowed
        )
        cols_by_table = self._group_columns(columns_rows, allowed, sequence_prerequisites_by_column)
        idxs_by_table = self._group_indexes(indexes_rows, allowed)
        cons_by_table = self._group_constraints(constraints_rows, allowed)
        enums_by_schema = self._group_enums(enums_rows, allowed)
        sequences_by_schema = self._group_sequences(sequences_rows or [], allowed)
        prerequisites_by_object = self._group_type_prerequisites(type_prerequisites_rows, allowed)
        prerequisites_by_table = {
            (schema_name, object_name): refs
            for (kind, schema_name, object_name, signature), refs in prerequisites_by_object.items()
            if kind is ObjectKind.TABLE and signature is None
        }
        composite_types_by_schema = self._group_composite_types(
            composite_types_rows, allowed, prerequisites_by_object
        )
        domain_types_by_schema = self._group_domain_types(
            domain_types_rows, allowed, prerequisites_by_object
        )
        functions_by_schema = self._group_functions(
            routines_rows or [], allowed, prerequisites_by_object
        )

        tables_by_schema, idxs_by_schema = self._build_tables(
            tables_rows,
            schema_names,
            cols_by_table,
            idxs_by_table,
            cons_by_table,
            prerequisites_by_table,
        )

        return Database(
            name="inspected",
            schemas=tuple(
                self._build_schemas(
                    schema_names,
                    tables_by_schema,
                    idxs_by_schema,
                    schemas_by_name,
                    enums_by_schema,
                    composite_types_by_schema,
                    domain_types_by_schema,
                    sequences_by_schema,
                    functions_by_schema,
                )
            ),
            extensions=tuple(extensions),
        )

    # ------------------------------------------------------------------
    # Grouping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _group_columns(
        rows: list[Any],
        allowed: set[str] | None,
        sequence_prerequisites: dict[tuple[str, str, str], list[ObjectRef]] | None = None,
    ) -> dict[tuple[str, str], list[Column]]:
        result: dict[tuple[str, str], list[Column]] = {}
        for row in rows:
            if allowed is not None and row.schema_name not in allowed:
                continue
            sequence_refs = (sequence_prerequisites or {}).get(
                (row.schema_name, row.table_name, row.column_name), []
            )
            result.setdefault((row.schema_name, row.table_name), []).append(
                _map_column(row, sequence_prerequisites=tuple(sequence_refs))
            )
        return result

    @staticmethod
    def _group_sequences(rows: list[Any], allowed: set[str] | None) -> dict[str, list[Sequence]]:
        result: dict[str, list[Sequence]] = {}
        for row in rows:
            if allowed is not None and row.schema_name not in allowed:
                continue
            owned_values = (row.owned_schema, row.owned_table, row.owned_column)
            if any(value is not None for value in owned_values) and not all(
                isinstance(value, str) and value for value in owned_values
            ):
                raise InspectionError(
                    f"Sequence {row.schema_name}.{row.sequence_name} has incomplete "
                    "OWNED BY metadata"
                )
            owned_by = None
            if all(value is not None for value in owned_values):
                owned_by = ObjectRef(
                    kind=ObjectKind.COLUMN,
                    qname=QualifiedName(namespace=row.owned_schema, name=row.owned_column),
                    parent=ObjectRef(
                        kind=ObjectKind.TABLE,
                        qname=QualifiedName(namespace=row.owned_schema, name=row.owned_table),
                    ),
                )
            sequence = Sequence(
                ref=ObjectRef(
                    kind=ObjectKind.SEQUENCE,
                    qname=QualifiedName(namespace=row.schema_name, name=row.sequence_name),
                ),
                data_type=row.data_type,
                start=row.start_value,
                increment=row.increment_by,
                min_value=row.min_value,
                max_value=row.max_value,
                cache=row.cache_size,
                cycle=row.cycle,
                owner=row.owner,
                owned_by=owned_by,
            )
            result.setdefault(row.schema_name, []).append(sequence)
        for sequences in result.values():
            sequences.sort(key=lambda sequence: sequence.ref.qname.name)
        return result

    @staticmethod
    def _group_sequence_prerequisites(
        rows: list[Any],
        allowed: set[str] | None,
    ) -> dict[tuple[str, str, str], list[ObjectRef]]:
        result: dict[tuple[str, str, str], set[ObjectRef]] = {}
        for row in rows:
            if allowed is not None and row.dependent_schema not in allowed:
                continue
            sequence_ref = ObjectRef(
                kind=ObjectKind.SEQUENCE,
                qname=QualifiedName(namespace=row.sequence_schema, name=row.sequence_name),
            )
            key = (row.dependent_schema, row.dependent_table, row.dependent_column)
            result.setdefault(key, set()).add(sequence_ref)
        return {
            key: sorted(refs, key=lambda ref: (ref.qname.namespace, ref.qname.name))
            for key, refs in result.items()
        }

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

    @staticmethod
    def _group_enums(rows: list[Any], allowed: set[str] | None) -> dict[str, list[EnumType]]:
        result: dict[str, list[EnumType]] = {}
        for row in rows:
            if allowed is not None and row.schema_name not in allowed:
                continue
            enum = EnumType(
                ref=ObjectRef(
                    kind=ObjectKind.ENUM,
                    qname=QualifiedName(namespace=row.schema_name, name=row.enum_name),
                ),
                labels=tuple(row.labels),
                owner=row.owner,
            )
            result.setdefault(row.schema_name, []).append(enum)
        for enums in result.values():
            enums.sort(key=lambda enum: enum.ref.qname.name)
        return result

    @staticmethod
    def _group_functions(
        rows: list[Any],
        allowed: set[str] | None,
        prerequisites: dict[tuple[ObjectKind, str, str, tuple[str, ...] | None], list[ObjectRef]],
    ) -> dict[str, list[Function]]:
        mode_by_code: dict[str, Literal["IN", "OUT", "INOUT", "VARIADIC", "TABLE"]] = {
            "i": "IN",
            "o": "OUT",
            "b": "INOUT",
            "v": "VARIADIC",
            "t": "TABLE",
        }
        result: dict[str, list[Function]] = {}
        for row in rows:
            schema_name = row.schema_name
            if allowed is not None and schema_name not in allowed:
                continue

            input_types = tuple(row.input_types or ())
            argument_types = tuple(row.all_argument_types or ())
            raw_modes = tuple(row.argument_modes or ("i" for _ in argument_types))
            raw_names = tuple(row.argument_names or (None for _ in argument_types))
            if len(argument_types) != len(raw_modes) or len(argument_types) != len(raw_names):
                raise InspectionError(
                    f"Function {schema_name}.{row.function_name} has inconsistent argument metadata"
                )

            arguments: list[FunctionArgument] = []
            for name, mode, data_type in zip(raw_names, raw_modes, argument_types, strict=True):
                mode_code = mode.decode() if isinstance(mode, bytes) else mode
                mapped_mode = mode_by_code.get(mode_code)
                if mapped_mode is None:
                    raise InspectionError(
                        f"Function {schema_name}.{row.function_name} has unsupported "
                        f"argument mode {mode!r}"
                    )
                if not isinstance(data_type, str) or not data_type.strip():
                    raise InspectionError(
                        f"Function {schema_name}.{row.function_name} has an unusable argument type"
                    )
                arguments.append(FunctionArgument(name=name, mode=mapped_mode, data_type=data_type))

            default_expressions = row.default_expressions
            if row.default_count and default_expressions is None:
                raise InspectionError(
                    f"Function {schema_name}.{row.function_name} has missing default expressions"
                )
            if default_expressions is not None and (
                not default_expressions.strip() or default_expressions.strip() == "?"
            ):
                raise InspectionError(
                    f"Function {schema_name}.{row.function_name} has unusable default expressions"
                )
            definition = row.definition
            if (
                not isinstance(definition, str)
                or not definition.strip()
                or definition.strip() == "?"
            ):
                raise InspectionError(
                    f"Function {schema_name}.{row.function_name} has no usable definition"
                )

            ref = ObjectRef(
                kind=ObjectKind.FUNCTION,
                qname=QualifiedName(namespace=schema_name, name=row.function_name),
                arg_signature=input_types,
            )
            function = Function(
                ref=ref,
                arguments=tuple(arguments),
                return_type=row.return_type,
                returns_set=row.returns_set,
                language=row.language,
                volatility=row.volatility,
                strict=row.strict,
                security_definer=row.security_definer,
                leakproof=row.leakproof,
                parallel=row.parallel,
                cost=row.cost,
                rows=row.rows,
                support_function=row.support_function,
                transforms=tuple(row.transforms or ()),
                config=tuple(row.config or ()),
                default_expressions=default_expressions,
                default_count=row.default_count,
                body=row.body,
                definition=definition,
                owner=row.owner,
                type_prerequisites=tuple(
                    prerequisites.get(
                        (ObjectKind.FUNCTION, schema_name, row.function_name, input_types), []
                    )
                ),
            )
            result.setdefault(schema_name, []).append(function)
        for functions in result.values():
            functions.sort(
                key=lambda function: (function.ref.qname.name, function.ref.arg_signature)
            )
        return result

    @staticmethod
    def _group_composite_types(
        rows: list[Any],
        allowed: set[str] | None,
        prerequisites: dict[tuple[ObjectKind, str, str, tuple[str, ...] | None], list[ObjectRef]],
    ) -> dict[str, list[CompositeType]]:
        grouped: dict[tuple[str, str], list[tuple[int, CompositeAttribute]]] = {}
        owners: dict[tuple[str, str], str | None] = {}
        for row in rows:
            schema_name = row.schema_name
            if allowed is not None and schema_name not in allowed:
                continue
            key = (schema_name, row.type_name)
            grouped.setdefault(key, [])
            owners[key] = row.owner
            if row.attribute_name is None:
                continue
            if row.attribute_position is None or row.data_type is None:
                raise InspectionError(
                    f"Composite attribute {schema_name}.{row.type_name}."
                    f"{row.attribute_name} is missing catalog metadata"
                )
            grouped[key].append(
                (
                    int(row.attribute_position),
                    CompositeAttribute(
                        name=row.attribute_name,
                        data_type=row.data_type,
                        collation=row.collation or None,
                    ),
                )
            )

        result: dict[str, list[CompositeType]] = {}
        for (schema_name, type_name), attributes in grouped.items():
            attributes.sort(key=lambda item: item[0])
            positions = [position for position, _ in attributes]
            if len(positions) != len(set(positions)):
                raise InspectionError(
                    f"Duplicate attribute position in composite type {schema_name}.{type_name}"
                )
            ref = ObjectRef(
                kind=ObjectKind.COMPOSITE_TYPE,
                qname=QualifiedName(namespace=schema_name, name=type_name),
            )
            composite = CompositeType(
                ref=ref,
                attributes=tuple(attribute for _, attribute in attributes),
                type_prerequisites=tuple(
                    prerequisites.get((ObjectKind.COMPOSITE_TYPE, schema_name, type_name, None), [])
                ),
                owner=owners[(schema_name, type_name)],
            )
            result.setdefault(schema_name, []).append(composite)
        for composites in result.values():
            composites.sort(key=lambda composite: composite.ref.qname.name)
        return result

    @staticmethod
    def _group_domain_types(
        rows: list[Any],
        allowed: set[str] | None,
        prerequisites: dict[tuple[ObjectKind, str, str, tuple[str, ...] | None], list[ObjectRef]],
    ) -> dict[str, list[DomainType]]:
        metadata: dict[tuple[str, str], tuple[Any, ...]] = {}
        checks: dict[tuple[str, str], list[DomainCheck]] = {}
        for row in rows:
            schema_name = row.schema_name
            if allowed is not None and schema_name not in allowed:
                continue
            key = (schema_name, row.domain_name)
            current_metadata = (
                row.base_type,
                row.collation,
                row.default_expr,
                row.not_null,
                row.owner,
                row.used_in_container,
            )
            previous_metadata = metadata.setdefault(key, current_metadata)
            if previous_metadata != current_metadata:
                raise InspectionError(
                    f"Domain {schema_name}.{row.domain_name} has inconsistent catalog metadata"
                )
            checks.setdefault(key, [])
            if row.check_name is None:
                continue
            if (
                row.check_expression is None
                or not row.check_expression.strip()
                or row.check_expression.strip() == "?"
                or row.check_validated is None
            ):
                raise InspectionError(
                    f"Domain check {schema_name}.{row.domain_name}.{row.check_name} "
                    "is missing a usable expression or validation state"
                )
            checks[key].append(
                DomainCheck(
                    name=row.check_name,
                    expression=row.check_expression,
                    validated=row.check_validated,
                )
            )

        result: dict[str, list[DomainType]] = {}
        for (schema_name, domain_name), values in metadata.items():
            base_type, collation, default_expr, not_null, owner, used_in_container = values
            if not isinstance(base_type, str) or not base_type.strip() or base_type.strip() == "?":
                raise InspectionError(f"Domain {schema_name}.{domain_name} has no usable base type")
            if default_expr is not None and (
                not default_expr.strip() or default_expr.strip() == "?"
            ):
                raise InspectionError(
                    f"Domain {schema_name}.{domain_name} has no usable default expression"
                )
            ref = ObjectRef(
                kind=ObjectKind.DOMAIN_TYPE,
                qname=QualifiedName(namespace=schema_name, name=domain_name),
            )
            domain = DomainType(
                ref=ref,
                base_type=base_type,
                collation=collation,
                default_expr=default_expr,
                not_null=not_null,
                checks=tuple(
                    sorted(checks[(schema_name, domain_name)], key=lambda check: check.name)
                ),
                type_prerequisites=tuple(
                    prerequisites.get((ObjectKind.DOMAIN_TYPE, schema_name, domain_name, None), [])
                ),
                used_in_container=used_in_container,
                owner=owner,
            )
            result.setdefault(schema_name, []).append(domain)
        for domains in result.values():
            domains.sort(key=lambda domain: domain.ref.qname.name)
        return result

    @staticmethod
    def _group_type_prerequisites(
        rows: list[Any],
        allowed: set[str] | None,
    ) -> dict[tuple[ObjectKind, str, str, tuple[str, ...] | None], list[ObjectRef]]:
        result: dict[tuple[ObjectKind, str, str, tuple[str, ...] | None], set[ObjectRef]] = {}
        for row in rows:
            if allowed is not None and row.dependent_schema not in allowed:
                continue
            dependent_kind = ObjectKind(row.dependent_kind)
            if dependent_kind not in {
                ObjectKind.TABLE,
                ObjectKind.COMPOSITE_TYPE,
                ObjectKind.DOMAIN_TYPE,
                ObjectKind.FUNCTION,
            }:
                raise InspectionError(f"Unsupported type prerequisite dependent {dependent_kind!r}")
            type_kind = ObjectKind(row.type_kind)
            if type_kind not in {
                ObjectKind.ENUM,
                ObjectKind.COMPOSITE_TYPE,
                ObjectKind.DOMAIN_TYPE,
            }:
                raise InspectionError(f"Unsupported type prerequisite kind {type_kind!r}")
            ref = ObjectRef(
                kind=type_kind,
                qname=QualifiedName(namespace=row.type_schema, name=row.type_name),
            )
            signature = None
            if dependent_kind is ObjectKind.FUNCTION:
                if row.dependent_signature is None:
                    raise InspectionError(
                        f"Function type prerequisite {row.dependent_schema}.{row.dependent_name} "
                        "has no overload signature"
                    )
                signature = tuple(row.dependent_signature)
            result.setdefault(
                (dependent_kind, row.dependent_schema, row.dependent_name, signature), set()
            ).add(ref)
        return {
            key: sorted(refs, key=lambda ref: (ref.qname.namespace, ref.qname.name))
            for key, refs in result.items()
        }

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
        type_prerequisites_by_table: dict[tuple[str, str], list[ObjectRef]] | None = None,
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
                    type_prerequisites=tuple((type_prerequisites_by_table or {}).get(key, [])),
                    unlogged=row.unlogged,
                    owner=row.owner,
                    tablespace=row.tablespace,
                    comment=row.comment,
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
        schemas_by_name: dict[str, Any],
        enums_by_schema: dict[str, list[EnumType]],
        composite_types_by_schema: dict[str, list[CompositeType]],
        domain_types_by_schema: dict[str, list[DomainType]],
        sequences_by_schema: dict[str, list[Sequence]],
        functions_by_schema: dict[str, list[Function]],
    ) -> list[Schema]:
        result: list[Schema] = []
        for name in schema_names:
            row = schemas_by_name[name]
            result.append(
                Schema(
                    ref=ObjectRef(
                        kind=ObjectKind.SCHEMA,
                        qname=QualifiedName(namespace=name, name=name),
                    ),
                    owner=row.owner,
                    tables=tuple(tables_by_schema.get(name, [])),
                    indexes=tuple(idxs_by_schema.get(name, [])),
                    enums=tuple(enums_by_schema.get(name, [])),
                    composite_types=tuple(composite_types_by_schema.get(name, [])),
                    domain_types=tuple(domain_types_by_schema.get(name, [])),
                    sequences=tuple(sequences_by_schema.get(name, [])),
                    functions=tuple(functions_by_schema.get(name, [])),
                    comment=row.comment,
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
                    installed_schema=row.installed_schema,
                    comment=row.comment,
                )
            )
        return result
