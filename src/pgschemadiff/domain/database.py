"""Database top-level aggregate (task P1-DOM-07).

:class:`Database` is the root of the domain graph.  It composes:

- A tuple of :class:`~pgschemadiff.domain.schema.Schema` objects.
- A tuple of :class:`~pgschemadiff.domain.extension.Extension` objects.

Lookup helpers keyed by :class:`~pgschemadiff.domain.identity.QualifiedName`
or :class:`~pgschemadiff.domain.identity.ObjectRef` allow callers to find
objects without manual iteration.

All models are pure domain: no IO, no async, no external drivers.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pgschemadiff.domain.composite_type import CompositeType
from pgschemadiff.domain.domain_type import DomainType
from pgschemadiff.domain.enum_type import EnumType
from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.function import Function
from pgschemadiff.domain.identity import ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index
from pgschemadiff.domain.procedure import Procedure
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.sequence import Sequence
from pgschemadiff.domain.table import Table


class Database(BaseModel):
    """Top-level aggregate representing an entire PostgreSQL database snapshot.

    Usage example::

        from pgschemadiff.domain.database import Database
        from pgschemadiff.domain.schema import Schema
        from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName

        pub_ref = ObjectRef(
            kind=ObjectKind.SCHEMA,
            qname=QualifiedName(namespace="public", name="public"),
        )
        pub = Schema(ref=pub_ref)
        db = Database(name="mydb", schemas=(pub,))

    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    """The database name (``pg_database.datname``)."""

    schemas: tuple[Schema, ...] = Field(default=())
    """All non-system schemas in the database."""

    extensions: tuple[Extension, ...] = Field(default=())
    """All installed extensions."""

    server_version: str | None = None
    """PostgreSQL server version string, e.g. ``"18.0"``."""

    @model_validator(mode="after")
    def _check_schema_name_uniqueness(self) -> Self:
        seen: set[str] = set()
        for schema in self.schemas:
            n = schema.name
            if n in seen:
                raise ValueError(f"Duplicate schema name {n!r} in database {self.name!r}")
            seen.add(n)
        return self

    @model_validator(mode="after")
    def _check_extension_name_uniqueness(self) -> Self:
        seen: set[str] = set()
        for ext in self.extensions:
            n = ext.name
            if n in seen:
                raise ValueError(f"Duplicate extension name {n!r} in database {self.name!r}")
            seen.add(n)
        return self

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def schema_by_name(self, name: str) -> Schema | None:
        """Return the schema with the given name, or ``None``."""
        for schema in self.schemas:
            if schema.name == name:
                return schema
        return None

    def table_by_qname(self, qname: QualifiedName) -> Table | None:
        """Return a table by its fully-qualified name, or ``None``."""
        schema = self.schema_by_name(qname.namespace)
        if schema is None:
            return None
        return schema.table_by_name(qname.name)

    def table_by_ref(self, ref: ObjectRef) -> Table | None:
        """Return a table by its :class:`ObjectRef`, or ``None``."""
        return self.table_by_qname(ref.qname)

    def index_by_qname(self, qname: QualifiedName) -> Index | None:
        """Return an index by its fully-qualified name, or ``None``.

        Indexes are looked up in the schema whose name matches
        ``qname.namespace``.
        """
        schema = self.schema_by_name(qname.namespace)
        if schema is None:
            return None
        for idx in schema.indexes:
            if idx.ref.qname.name == qname.name:
                return idx
        return None

    def index_by_ref(self, ref: ObjectRef) -> Index | None:
        """Return an index by its :class:`ObjectRef`, or ``None``."""
        return self.index_by_qname(ref.qname)

    def extension_by_name(self, name: str) -> Extension | None:
        """Return the extension with the given name, or ``None``."""
        for ext in self.extensions:
            if ext.name == name:
                return ext
        return None

    # ------------------------------------------------------------------
    # Aggregate helpers
    # ------------------------------------------------------------------

    def all_tables(self) -> tuple[Table, ...]:
        """Return all tables across every schema, in schema-then-table order."""
        result: list[Table] = []
        for schema in self.schemas:
            result.extend(schema.tables)
        return tuple(result)

    def all_enums(self) -> tuple[EnumType, ...]:
        """Return all enum types across schemas, in schema-then-name order."""
        result: list[EnumType] = []
        for schema in self.schemas:
            result.extend(schema.enums)
        return tuple(result)

    def all_composite_types(self) -> tuple[CompositeType, ...]:
        """Return all composite types across schemas, in schema-then-name order."""
        result: list[CompositeType] = []
        for schema in self.schemas:
            result.extend(schema.composite_types)
        return tuple(result)

    def all_domain_types(self) -> tuple[DomainType, ...]:
        """Return all domains across schemas, in schema-then-name order."""
        result: list[DomainType] = []
        for schema in self.schemas:
            result.extend(schema.domain_types)
        return tuple(result)

    def all_sequences(self) -> tuple[Sequence, ...]:
        """Return all sequences across every schema."""
        result: list[Sequence] = []
        for schema in self.schemas:
            result.extend(schema.sequences)
        return tuple(result)

    def all_functions(self) -> tuple[Function, ...]:
        """Return all functions across every schema."""
        result: list[Function] = []
        for schema in self.schemas:
            result.extend(schema.functions)
        return tuple(result)

    def all_procedures(self) -> tuple[Procedure, ...]:
        """Return all procedures across every schema."""
        result: list[Procedure] = []
        for schema in self.schemas:
            result.extend(schema.procedures)
        return tuple(result)

    def all_indexes(self) -> tuple[Index, ...]:
        """Return all indexes across every schema."""
        result: list[Index] = []
        for schema in self.schemas:
            result.extend(schema.indexes)
        return tuple(result)
