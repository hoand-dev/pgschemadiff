"""Schema domain model (task P1-DOM-06).

:class:`Schema` represents a PostgreSQL namespace (``pg_namespace``) together
with the objects it contains.  For the MVP-A phase the collections hold the
object types that the diff engine already supports — tables and indexes.
Views, functions, sequences, etc. will be added in later phases without
changing the frozen-model contract.

All models are pure domain: no IO, no async, no external drivers.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index
from pgschemadiff.domain.table import Table


class Schema(BaseModel):
    """A PostgreSQL schema (namespace) with its owned objects.

    Usage example::

        from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
        from pgschemadiff.domain.schema import Schema

        ref = ObjectRef(
            kind=ObjectKind.SCHEMA,
            qname=QualifiedName(namespace="public", name="public"),
        )
        schema = Schema(ref=ref, owner="postgres")

    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: ObjectRef
    """Stable identity reference.  Must be of kind ``SCHEMA``."""

    owner: str | None = None
    """Database role that owns this schema (``pg_namespace.nspowner`` resolved
    to a role name).  ``None`` when not yet resolved."""

    tables: tuple[Table, ...] = Field(default=())
    """Tables contained in this schema, ordered by table name."""

    indexes: tuple[Index, ...] = Field(default=())
    """Indexes belonging to tables in this schema."""

    comment: str | None = None
    """Optional ``COMMENT ON SCHEMA`` value."""

    @model_validator(mode="after")
    def _check_ref_kind(self) -> Self:
        if self.ref.kind is not ObjectKind.SCHEMA:
            raise ValueError(f"Schema.ref must have kind SCHEMA, got {self.ref.kind!r}")
        return self

    @model_validator(mode="after")
    def _check_table_namespace_consistency(self) -> Self:
        """All tables must belong to this schema's namespace."""
        schema_name = self.ref.qname.name
        for table in self.tables:
            tbl_ns = table.ref.qname.namespace
            if tbl_ns != schema_name:
                raise ValueError(
                    f"Table {table.ref.qname.fqn!r} belongs to namespace {tbl_ns!r}, "
                    f"but schema is {schema_name!r}"
                )
        return self

    @property
    def name(self) -> str:
        """The schema name (``pg_namespace.nspname``)."""
        return self.ref.qname.name

    @property
    def qname(self) -> QualifiedName:
        """Shortcut to ``self.ref.qname``."""
        return self.ref.qname

    def table_by_name(self, name: str) -> Table | None:
        """Return the table with the given local name, or ``None``."""
        for tbl in self.tables:
            if tbl.ref.qname.name == name:
                return tbl
        return None
