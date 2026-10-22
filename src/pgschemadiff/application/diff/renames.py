"""Typed explicit rename annotations for schema diffs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pgschemadiff.domain.identity import QualifiedName
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from pgschemadiff.domain.database import Database


class TableRename(BaseModel):
    """Explicit mapping between a table's source and target identities."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: QualifiedName
    target: QualifiedName


class ColumnRename(BaseModel):
    """Explicit mapping between columns in a logical source/target table pair."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_table: QualifiedName
    source_name: str = Field(min_length=1)
    target_table: QualifiedName
    target_name: str = Field(min_length=1)


class RenameAnnotations(BaseModel):
    """Validated table and column mappings supplied explicitly by the user."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tables: tuple[TableRename, ...] = ()
    columns: tuple[ColumnRename, ...] = ()

    @classmethod
    def from_document(cls, document: object) -> Self:
        """Parse the common YAML/TOML ``renames`` document shape."""
        if not isinstance(document, Mapping) or set(document) != {"renames"}:
            raise DiffError("Rename document must contain only a 'renames' list")

        entries = document["renames"]
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
            raise DiffError("Rename document 'renames' value must be a list")

        try:
            tables: list[TableRename] = []
            columns: list[ColumnRename] = []
            for index, entry in enumerate(entries):
                if not isinstance(entry, Mapping) or set(entry) != {"kind", "from", "to"}:
                    raise DiffError(
                        f"Rename entry {index} must contain exactly 'kind', 'from', and 'to'"
                    )

                kind = entry["kind"]
                if kind == "table":
                    source_parts = _parse_path(entry["from"], expected_parts=2)
                    target_parts = _parse_path(entry["to"], expected_parts=2)
                    tables.append(
                        TableRename(
                            source=QualifiedName(namespace=source_parts[0], name=source_parts[1]),
                            target=QualifiedName(namespace=target_parts[0], name=target_parts[1]),
                        )
                    )
                elif kind == "column":
                    source_parts = _parse_path(entry["from"], expected_parts=3)
                    target_parts = _parse_path(entry["to"], expected_parts=3)
                    columns.append(
                        ColumnRename(
                            source_table=QualifiedName(
                                namespace=source_parts[0], name=source_parts[1]
                            ),
                            source_name=source_parts[2],
                            target_table=QualifiedName(
                                namespace=target_parts[0], name=target_parts[1]
                            ),
                            target_name=target_parts[2],
                        )
                    )
                else:
                    raise DiffError(f"Unsupported rename kind at entry {index}: {kind!r}")

            return cls(tables=tuple(tables), columns=tuple(columns))
        except DiffError:
            raise
        except ValueError as exc:
            raise DiffError(f"Invalid rename annotations: {exc}") from exc

    @model_validator(mode="after")
    def _check_mappings(self) -> Self:
        _validate_mapping(((rename.source, rename.target) for rename in self.tables), "table")
        _validate_mapping(
            (
                (
                    (rename.source_table, rename.source_name),
                    (rename.target_table, rename.target_name),
                )
                for rename in self.columns
            ),
            "column",
        )

        table_map = {rename.source: rename.target for rename in self.tables}
        for rename in self.columns:
            mapped_table = table_map.get(rename.source_table, rename.source_table)
            if mapped_table != rename.target_table:
                raise ValueError(
                    "Column rename must stay in the same table or follow an explicit table rename"
                )
        return self

    def table_target(self, source: QualifiedName) -> QualifiedName | None:
        """Return explicitly mapped target identity for *source*, if any."""
        return next((item.target for item in self.tables if item.source == source), None)

    def column_targets(
        self,
        source_table: QualifiedName,
        target_table: QualifiedName,
    ) -> dict[str, str]:
        """Return source-to-target column names for one paired table."""
        return {
            item.source_name: item.target_name
            for item in self.columns
            if item.source_table == source_table and item.target_table == target_table
        }

    def map_table(self, source: QualifiedName) -> QualifiedName:
        """Map a source table identity to its annotated target identity."""
        return self.table_target(source) or source

    def validate_for(self, source: Database, target: Database) -> None:
        """Validate annotation endpoints and collisions against both snapshots."""
        source_tables = {table.ref.qname: table for table in source.all_tables()}
        target_tables = {table.ref.qname: table for table in target.all_tables()}
        table_sources = {item.source for item in self.tables}
        table_targets = {item.target for item in self.tables}

        for table_rename in self.tables:
            if table_rename.source not in source_tables:
                raise DiffError(
                    f"Rename source table {table_rename.source.fqn} not found in source"
                )
            if table_rename.target not in target_tables:
                raise DiffError(
                    f"Rename target table {table_rename.target.fqn} not found in target"
                )
            if table_rename.source in target_tables and table_rename.source not in table_targets:
                raise DiffError(
                    f"Rename source table {table_rename.source.fqn} still exists in target"
                )
            if table_rename.target in source_tables and table_rename.target not in table_sources:
                raise DiffError(
                    f"Rename target table {table_rename.target.fqn} already exists in source"
                )

        column_sources = {(item.source_table, item.source_name) for item in self.columns}
        column_targets = {(item.target_table, item.target_name) for item in self.columns}
        for column_rename in self.columns:
            source_table = source_tables.get(column_rename.source_table)
            target_table = target_tables.get(column_rename.target_table)
            if source_table is None:
                raise DiffError(
                    f"Column rename source table {column_rename.source_table.fqn} not found"
                )
            if target_table is None:
                raise DiffError(
                    f"Column rename target table {column_rename.target_table.fqn} not found"
                )
            if source_table.column_by_name(column_rename.source_name) is None:
                raise DiffError(
                    f"Rename source column {column_rename.source_table.fqn}."
                    f"{column_rename.source_name} not found"
                )
            if target_table.column_by_name(column_rename.target_name) is None:
                raise DiffError(
                    f"Rename target column {column_rename.target_table.fqn}."
                    f"{column_rename.target_name} not found"
                )
            if (
                target_table.column_by_name(column_rename.source_name) is not None
                and (column_rename.target_table, column_rename.source_name) not in column_targets
            ):
                raise DiffError(
                    f"Rename source column {column_rename.source_name!r} still exists "
                    "in target table"
                )
            if (
                source_table.column_by_name(column_rename.target_name) is not None
                and (column_rename.source_table, column_rename.target_name) not in column_sources
            ):
                raise DiffError(
                    f"Rename target column {column_rename.target_name!r} already exists "
                    "in source table"
                )


def _parse_path(value: object, *, expected_parts: int) -> tuple[str, ...]:
    """Parse dot-separated PostgreSQL identifiers, honoring quoted dots."""
    if not isinstance(value, str) or not value:
        raise DiffError("Rename paths must be non-empty strings")

    parts: list[str] = []
    index = 0
    while index < len(value):
        part, index = _parse_identifier(value, index)
        parts.append(part)
        if index == len(value):
            break
        if value[index] != ".":
            raise DiffError(f"Expected '.' after identifier in rename path {value!r}")
        index += 1
        if index == len(value):
            raise DiffError(f"Rename path cannot end with '.' ({value!r})")

    if len(parts) != expected_parts:
        raise DiffError(
            f"Rename path {value!r} must contain {expected_parts} identifiers, got {len(parts)}"
        )
    return tuple(parts)


def _parse_identifier(value: str, index: int) -> tuple[str, int]:
    """Parse one quoted or unquoted PostgreSQL identifier."""
    if value[index] == '"':
        return _parse_quoted_identifier(value, index + 1)

    start = index
    while index < len(value) and value[index] not in '."':
        char = value[index]
        if not (char.isalpha() or char.isdigit() or char in "_$"):
            raise DiffError(f"Invalid unquoted identifier in rename path {value!r}")
        index += 1

    identifier = value[start:index]
    if not identifier or not (identifier[0].isalpha() or identifier[0] == "_"):
        raise DiffError(f"Invalid unquoted identifier in rename path {value!r}")
    return identifier.lower(), index


def _parse_quoted_identifier(value: str, index: int) -> tuple[str, int]:
    """Parse quoted identifier, including doubled quote escapes."""
    chars: list[str] = []
    while index < len(value):
        char = value[index]
        if char != '"':
            if char == "\0":
                raise DiffError("PostgreSQL identifiers cannot contain NUL")
            chars.append(char)
            index += 1
            continue
        if index + 1 < len(value) and value[index + 1] == '"':
            chars.append('"')
            index += 2
            continue

        identifier = "".join(chars)
        if not identifier:
            raise DiffError("PostgreSQL identifiers cannot be empty")
        return identifier, index + 1

    raise DiffError(f"Unterminated quoted identifier in rename path {value!r}")


def _validate_mapping(pairs: Iterable[tuple[object, object]], label: str) -> None:
    """Reject duplicate endpoints, no-ops, and rename cycles."""
    pair_list = tuple(pairs)
    mapping = dict(pair_list)
    pair_count = len(pair_list)
    if len(mapping) != pair_count:
        raise ValueError(f"Duplicate {label} rename source")
    if len(set(mapping.values())) != pair_count:
        raise ValueError(f"Multiple {label} renames target the same object")
    if any(source == target for source, target in mapping.items()):
        raise ValueError(f"No-op {label} rename is not allowed")

    for start in mapping:
        visited: set[object] = set()
        current = start
        while current in mapping:
            if current in visited:
                raise ValueError(f"Cyclic {label} renames are not supported")
            visited.add(current)
            current = mapping[current]


__all__ = ["ColumnRename", "RenameAnnotations", "TableRename"]
