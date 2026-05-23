"""Identity primitives shared by every domain model.

Every PostgreSQL object the diff engine handles is identified by an
:class:`ObjectRef`.  Top-level objects (tables, views, indexes, functions, ...)
carry a :class:`QualifiedName`; sub-objects (columns, constraints, triggers,
policies) additionally carry a ``parent`` :class:`ObjectRef` pointing at the
table that owns them.

This module is the foundation of the domain layer: it must remain pure
(no IO, no async, no external drivers).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ObjectKind(StrEnum):
    """Every kind of PostgreSQL object pgschemadiff knows how to compare."""

    SCHEMA = "schema"
    EXTENSION = "extension"
    TABLE = "table"
    VIEW = "view"
    MATERIALIZED_VIEW = "materialized_view"
    INDEX = "index"
    SEQUENCE = "sequence"
    FUNCTION = "function"
    PROCEDURE = "procedure"
    ENUM = "enum"
    COMPOSITE_TYPE = "composite_type"
    DOMAIN_TYPE = "domain_type"
    COLUMN = "column"
    CONSTRAINT = "constraint"
    TRIGGER = "trigger"
    POLICY = "policy"


SUB_OBJECT_KINDS: frozenset[ObjectKind] = frozenset(
    {
        ObjectKind.COLUMN,
        ObjectKind.CONSTRAINT,
        ObjectKind.TRIGGER,
        ObjectKind.POLICY,
    }
)

_OVERLOADED_KINDS: frozenset[ObjectKind] = frozenset({ObjectKind.FUNCTION, ObjectKind.PROCEDURE})


def _quote_ident(value: str) -> str:
    """Quote a PostgreSQL identifier per the standard rule.

    A literal ``"`` inside the identifier is doubled, then the whole value is
    wrapped in double quotes. This matches what ``pg_catalog.quote_ident``
    produces for identifiers that need quoting.
    """
    return '"' + value.replace('"', '""') + '"'


class QualifiedName(BaseModel):
    """``namespace.name`` pair, immutable and value-equal.

    ``namespace`` matches PostgreSQL's ``pg_namespace.nspname``; we avoid the
    English word "schema" here because it shadows :meth:`pydantic.BaseModel.schema`
    and confuses both type checkers and humans (the project itself is *about*
    schemas — the word would be overloaded).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    namespace: str = Field(min_length=1)
    name: str = Field(min_length=1)

    @property
    def fqn(self) -> str:
        """SQL-safe ``"namespace"."name"`` form (identifiers double-quoted)."""
        return f"{_quote_ident(self.namespace)}.{_quote_ident(self.name)}"

    def __str__(self) -> str:
        return self.fqn


class ObjectRef(BaseModel):
    """Stable reference to a PostgreSQL object.

    For top-level objects, ``parent`` is ``None`` and ``qname`` is the object's
    own qualified name. For sub-objects (column, constraint, trigger, policy),
    ``parent`` references the owning table and ``qname.name`` is the local
    name within that table; ``qname.schema`` mirrors the parent's schema for
    convenience.

    Functions and procedures additionally carry ``arg_signature`` because
    PostgreSQL allows overloading.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ObjectKind
    qname: QualifiedName
    parent: ObjectRef | None = None
    arg_signature: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        is_sub_object = self.kind in SUB_OBJECT_KINDS
        if is_sub_object:
            if self.parent is None:
                raise ValueError(f"ObjectRef of kind {self.kind!r} requires a parent ObjectRef")
            if self.parent.kind is not ObjectKind.TABLE:
                raise ValueError(
                    f"ObjectRef of kind {self.kind!r} must have a TABLE parent, "
                    f"got {self.parent.kind!r}"
                )
        elif self.parent is not None:
            raise ValueError(f"ObjectRef of kind {self.kind!r} must not have a parent")

        needs_signature = self.kind in _OVERLOADED_KINDS
        if needs_signature and self.arg_signature is None:
            raise ValueError(
                f"ObjectRef of kind {self.kind!r} requires arg_signature for overloading"
            )
        if not needs_signature and self.arg_signature is not None:
            raise ValueError(f"ObjectRef of kind {self.kind!r} must not carry arg_signature")
        return self


ObjectRef.model_rebuild()
