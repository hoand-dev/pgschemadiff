"""Schema- and extension-level delta subclasses (task P2-DOM-01f).

Defines concrete :class:`~pgschemadiff.domain.delta.base.DeltaBase` subclasses
for schema- and extension-level DDL operations:

- :class:`CreateSchema` — ``CREATE SCHEMA``
- :class:`DropSchema` — ``DROP SCHEMA``
- :class:`CreateExtension` — ``CREATE EXTENSION``
- :class:`DropExtension` — ``DROP EXTENSION``
- :class:`AlterExtension` — ``ALTER EXTENSION … UPDATE TO`` / ``SET SCHEMA``

Each subclass narrows ``op`` to ``Literal[DeltaOp.X]`` (the coarse semantic
operation) AND declares a globally-unique ``kind`` string field that acts as
the **union discriminator** for both the local category aliases (:data:`SchemaDelta`
and :data:`ExtensionDelta`) and the global ``Delta`` union assembled at the
bottom of :mod:`pgschemadiff.domain.delta.base`.

``kind`` convention
-------------------
Every concrete delta class across *all* object categories carries a ``kind``
field whose value is globally unique — no two concrete classes in any category
(table / column / index / constraint / schema / extension / …) share the same
``kind`` string.  This guarantees that the global ``Delta`` union::

    Delta = Annotated[
        TableDelta | ColumnDelta | IndexDelta | ConstraintDelta | SchemaDelta | ExtensionDelta,
        Field(discriminator="kind"),
    ]

can discriminate on a single field without ambiguity.

``op`` (CREATE/DROP/ALTER/RENAME/…) is deliberately kept as a *coarse*
semantic filter — it is intentionally shared across categories.  Discriminating
a global union on ``op`` alone would raise ``TypeError`` because, for example,
both ``CreateSchema`` and ``CreateTable`` map ``op`` to ``"create"``.  Using
``kind`` avoids that collision entirely.

``kind`` values chosen for this module:

+--------------------------+---------------------------+
| Class                    | ``kind`` value            |
+==========================+===========================+
| :class:`CreateSchema`    | ``"create_schema"``       |
+--------------------------+---------------------------+
| :class:`DropSchema`      | ``"drop_schema"``         |
+--------------------------+---------------------------+
| :class:`CreateExtension` | ``"create_extension"``    |
+--------------------------+---------------------------+
| :class:`DropExtension`   | ``"drop_extension"``      |
+--------------------------+---------------------------+
| :class:`AlterExtension`  | ``"alter_extension"``     |
+--------------------------+---------------------------+

Target / identity — top-level objects
--------------------------------------
Both :class:`ObjectKind.SCHEMA` and :class:`ObjectKind.EXTENSION` are
**top-level** object kinds — they are NOT listed in
:data:`~pgschemadiff.domain.identity.SUB_OBJECT_KINDS`.  Therefore:

* ``target.parent`` must be ``None`` (enforced by
  :class:`~pgschemadiff.domain.identity.ObjectRef`'s own validator).
* The :meth:`~pgschemadiff.domain.delta.base.DeltaBase.sort_key` takes the
  3-tuple form ``(namespace, object_name, op_value)``.

Schema creation semantics
--------------------------
:class:`CreateSchema` carries the full :class:`~pgschemadiff.domain.schema.Schema`
aggregate (including its ``owner`` and ``comment``), but NOT the tables or
indexes the schema will eventually contain.  Those objects arrive as separate
:class:`~pgschemadiff.domain.delta.table.CreateTable` / ``CreateIndex`` deltas
that the topo-sorter orders after the ``CreateSchema``.  This mirrors how
:class:`~pgschemadiff.domain.delta.table.CreateTable` carries the full
:class:`~pgschemadiff.domain.table.Table` aggregate independently of the schema.

Field naming note
------------------
The payload field carrying the :class:`~pgschemadiff.domain.schema.Schema`
aggregate is named ``pg_schema`` (not ``schema``) to avoid shadowing
:meth:`pydantic.BaseModel.schema` — the deprecated JSON-schema class method
inherited from Pydantic's ``BaseModel``.  Mypy treats ``schema`` as a type
conflict; ``pg_schema`` removes the ambiguity while remaining readable.

Extension update semantics
---------------------------
:class:`AlterExtension` covers two mutually non-exclusive PostgreSQL DDL forms:

* ``ALTER EXTENSION name UPDATE TO 'version'`` (``new_version`` field)
* ``ALTER EXTENSION name SET SCHEMA schema_name`` (``new_schema`` field)

Both fields are ``str | None``; ``None`` means that aspect has not changed.
The validator rejects the all-``None`` no-op (mirroring
:class:`~pgschemadiff.domain.delta.table.AlterTableAttrs`).

Design notes
------------
* Table / column / index / constraint deltas are **not** modelled here; those
  are P2-DOM-01b / P2-DOM-01c / P2-DOM-01d / P2-DOM-01e.
* Models are pure domain: no IO, no async, no external drivers.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp
from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.identity import ObjectKind
from pgschemadiff.domain.schema import Schema

# ---------------------------------------------------------------------------
# CreateSchema
# ---------------------------------------------------------------------------


class CreateSchema(DeltaBase):
    """Delta for ``CREATE SCHEMA schema_name [AUTHORIZATION owner]``.

    Carries the full :class:`~pgschemadiff.domain.schema.Schema` aggregate
    (owner, comment) so the SQL emitter has all the information it needs
    without additional lookups.

    The tables and indexes the schema will eventually contain are NOT included
    here — they arrive as separate
    :class:`~pgschemadiff.domain.delta.table.CreateTable` /
    :class:`~pgschemadiff.domain.delta.index.CreateIndex` deltas that the
    topo-sorter orders after this ``CreateSchema``.  This keeps each delta
    self-contained and the topo-sort DAG clean.

    ``target`` (inherited from :class:`~pgschemadiff.domain.delta.base.DeltaBase`)
    must equal ``pg_schema.ref`` for identity consistency; the validator enforces
    this at construction time.  Additionally, ``target.kind`` must be
    ``ObjectKind.SCHEMA`` (also validated).

    The :meth:`~pgschemadiff.domain.delta.base.DeltaBase.sort_key` is the
    3-tuple ``(namespace, schema_name, "create")`` because ``SCHEMA`` is a
    top-level kind (not in ``SUB_OBJECT_KINDS``).

    ``kind`` is the globally-unique union discriminator for ``CreateSchema``.
    """

    op: Literal[DeltaOp.CREATE] = DeltaOp.CREATE
    kind: Literal["create_schema"] = "create_schema"

    pg_schema: Schema
    """The new schema to create.  Carries owner and comment.

    Named ``pg_schema`` (not ``schema``) to avoid shadowing
    :meth:`pydantic.BaseModel.schema` — see module docstring.
    """

    @model_validator(mode="after")
    def _check_target_matches_schema_ref(self) -> Self:
        if self.target.kind is not ObjectKind.SCHEMA:
            raise ValueError(
                f"CreateSchema.target.kind must be ObjectKind.SCHEMA, got {self.target.kind!r}"
            )
        if self.target != self.pg_schema.ref:
            raise ValueError(
                f"CreateSchema.target {self.target!r} must equal schema.ref {self.pg_schema.ref!r}"
            )
        return self


# ---------------------------------------------------------------------------
# DropSchema
# ---------------------------------------------------------------------------


class DropSchema(DeltaBase):
    """Delta for ``DROP SCHEMA schema_name [CASCADE | RESTRICT]``.

    Carries the full :class:`~pgschemadiff.domain.schema.Schema` aggregate so
    the risk classifier and SQL emitter can inspect what is being dropped
    (e.g. owner, whether it has tables — which would require ``CASCADE``).

    ``target`` must equal ``pg_schema.ref`` for identity consistency; the
    validator enforces this at construction time.

    The :meth:`~pgschemadiff.domain.delta.base.DeltaBase.sort_key` is the
    3-tuple ``(namespace, schema_name, "drop")``.

    ``kind`` is the globally-unique union discriminator for ``DropSchema``.
    """

    op: Literal[DeltaOp.DROP] = DeltaOp.DROP
    kind: Literal["drop_schema"] = "drop_schema"

    pg_schema: Schema
    """The schema being dropped.

    Named ``pg_schema`` (not ``schema``) to avoid shadowing
    :meth:`pydantic.BaseModel.schema` — see module docstring.
    """

    @model_validator(mode="after")
    def _check_target_matches_schema_ref(self) -> Self:
        if self.target != self.pg_schema.ref:
            raise ValueError(
                f"DropSchema.target {self.target!r} must equal schema.ref {self.pg_schema.ref!r}"
            )
        return self


# ---------------------------------------------------------------------------
# CreateExtension
# ---------------------------------------------------------------------------


class CreateExtension(DeltaBase):
    """Delta for ``CREATE EXTENSION [IF NOT EXISTS] name [WITH] [SCHEMA schema]``.

    Carries the full :class:`~pgschemadiff.domain.extension.Extension` aggregate
    (version, installed_schema, comment) so the SQL emitter has all the
    information it needs without additional lookups.

    ``target`` (inherited from :class:`~pgschemadiff.domain.delta.base.DeltaBase`)
    must equal ``extension.ref`` for identity consistency; the validator enforces
    this at construction time.  Additionally, ``target.kind`` must be
    ``ObjectKind.EXTENSION`` (also validated).

    The :meth:`~pgschemadiff.domain.delta.base.DeltaBase.sort_key` is the
    3-tuple ``(namespace, extension_name, "create")`` because ``EXTENSION`` is a
    top-level kind (not in ``SUB_OBJECT_KINDS``).

    ``kind`` is the globally-unique union discriminator for ``CreateExtension``.
    """

    op: Literal[DeltaOp.CREATE] = DeltaOp.CREATE
    kind: Literal["create_extension"] = "create_extension"

    extension: Extension
    """The extension to create.  Carries version, installed_schema, and comment."""

    @model_validator(mode="after")
    def _check_target_matches_extension_ref(self) -> Self:
        if self.target.kind is not ObjectKind.EXTENSION:
            raise ValueError(
                f"CreateExtension.target.kind must be ObjectKind.EXTENSION, "
                f"got {self.target.kind!r}"
            )
        if self.target != self.extension.ref:
            raise ValueError(
                f"CreateExtension.target {self.target!r} must equal "
                f"extension.ref {self.extension.ref!r}"
            )
        return self


# ---------------------------------------------------------------------------
# DropExtension
# ---------------------------------------------------------------------------


class DropExtension(DeltaBase):
    """Delta for ``DROP EXTENSION [IF EXISTS] name [CASCADE | RESTRICT]``.

    Carries the full :class:`~pgschemadiff.domain.extension.Extension` aggregate
    so the risk classifier and SQL emitter can inspect what is being dropped
    (e.g. which schema it was installed in).

    ``target`` must equal ``extension.ref`` for identity consistency; the
    validator enforces this at construction time.

    The :meth:`~pgschemadiff.domain.delta.base.DeltaBase.sort_key` is the
    3-tuple ``(namespace, extension_name, "drop")``.

    ``kind`` is the globally-unique union discriminator for ``DropExtension``.
    """

    op: Literal[DeltaOp.DROP] = DeltaOp.DROP
    kind: Literal["drop_extension"] = "drop_extension"

    extension: Extension
    """The extension being dropped."""

    @model_validator(mode="after")
    def _check_target_matches_extension_ref(self) -> Self:
        if self.target != self.extension.ref:
            raise ValueError(
                f"DropExtension.target {self.target!r} must equal "
                f"extension.ref {self.extension.ref!r}"
            )
        return self


# ---------------------------------------------------------------------------
# AlterExtension
# ---------------------------------------------------------------------------


class AlterExtension(DeltaBase):
    """Delta for extension-level attribute changes without reinstallation.

    Covers two PostgreSQL DDL forms that can be combined in a single delta:

    * ``ALTER EXTENSION name UPDATE TO 'new_version'``
      (``new_version`` field; ``None`` if the version is not changing)
    * ``ALTER EXTENSION name SET SCHEMA new_schema``
      (``new_schema`` field; ``None`` if the schema is not changing)

    Each optional field is ``None`` when that aspect has not changed.  At least
    one field must be non-``None`` (enforced by validator) — an all-``None``
    ``AlterExtension`` is semantically a no-op and is rejected at construction
    time, mirroring the behaviour of
    :class:`~pgschemadiff.domain.delta.table.AlterTableAttrs`.

    ``target.kind`` must be ``ObjectKind.EXTENSION``; the validator enforces
    this.

    The :meth:`~pgschemadiff.domain.delta.base.DeltaBase.sort_key` is the
    3-tuple ``(namespace, extension_name, "alter")``.

    ``kind`` is the globally-unique union discriminator for ``AlterExtension``.
    """

    op: Literal[DeltaOp.ALTER] = DeltaOp.ALTER
    kind: Literal["alter_extension"] = "alter_extension"

    new_version: str | None = None
    """New version string, or ``None`` if the version is not changing.

    When set, the emitter generates:
    ``ALTER EXTENSION name UPDATE TO 'new_version'``
    """

    new_schema: str | None = None
    """New schema name, or ``None`` if the schema relocation is not changing.

    When set, the emitter generates:
    ``ALTER EXTENSION name SET SCHEMA new_schema``
    """

    @model_validator(mode="after")
    def _check_target_kind_and_at_least_one_change(self) -> Self:
        if self.target.kind is not ObjectKind.EXTENSION:
            raise ValueError(
                f"AlterExtension.target.kind must be ObjectKind.EXTENSION, got {self.target.kind!r}"
            )
        if self.new_version is None and self.new_schema is None:
            raise ValueError(
                "AlterExtension must change at least one attribute; "
                "both new_version and new_schema are None (no-op)"
            )
        return self


# ---------------------------------------------------------------------------
# Discriminated union aliases
# ---------------------------------------------------------------------------

SchemaDelta = Annotated[
    CreateSchema | DropSchema,
    Field(discriminator="kind"),
]
"""Pydantic discriminated union over the two schema-level delta variants.

The ``kind`` literal field drives Pydantic's discriminator logic::

    from pydantic import TypeAdapter
    from pgschemadiff.domain.delta.schema import SchemaDelta

    ta: TypeAdapter[SchemaDelta] = TypeAdapter(SchemaDelta)
    delta = ta.validate_python(
        {"kind": "create_schema", "op": "create", "target": ..., "pg_schema": ...}
    )

This alias is included verbatim in the global ``Delta`` union assembled at the
bottom of :mod:`pgschemadiff.domain.delta.base`.  Each ``kind`` value is
globally unique across all object categories, so there is no collision risk
when the global union discriminates on ``kind``.
"""

ExtensionDelta = Annotated[
    CreateExtension | DropExtension | AlterExtension,
    Field(discriminator="kind"),
]
"""Pydantic discriminated union over all three extension-level delta variants.

The ``kind`` literal field drives Pydantic's discriminator logic::

    from pydantic import TypeAdapter
    from pgschemadiff.domain.delta.schema import ExtensionDelta

    ta: TypeAdapter[ExtensionDelta] = TypeAdapter(ExtensionDelta)
    delta = ta.validate_python(
        {"kind": "create_extension", "op": "create", "target": ..., "extension": ...}
    )

This alias is included verbatim in the global ``Delta`` union assembled at the
bottom of :mod:`pgschemadiff.domain.delta.base`.  Each ``kind`` value is
globally unique across all object categories, so there is no collision risk
when the global union discriminates on ``kind``.
"""

__all__: list[str] = [
    "AlterExtension",
    "CreateExtension",
    "CreateSchema",
    "DropExtension",
    "DropSchema",
    "ExtensionDelta",
    "SchemaDelta",
]
