"""Extension domain model (task P1-DOM-06).

:class:`Extension` represents a PostgreSQL extension installed in a database,
as introspected from ``pg_extension``.

All models are pure domain: no IO, no async, no external drivers.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pgschemadiff.domain.identity import ObjectKind, ObjectRef


class Extension(BaseModel):
    """A PostgreSQL extension installed in a database.

    Usage example::

        from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
        from pgschemadiff.domain.extension import Extension

        ref = ObjectRef(
            kind=ObjectKind.EXTENSION,
            qname=QualifiedName(namespace="public", name="pgcrypto"),
        )
        ext = Extension(ref=ref, version="1.3")

    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: ObjectRef
    """Stable identity reference.  Must be of kind ``EXTENSION``."""

    version: str = Field(min_length=1)
    """Installed version string (``pg_extension.extversion``)."""

    installed_schema: str | None = None
    """The schema into which the extension objects were installed
    (``pg_extension.extnamespace`` resolved to a name).
    ``None`` if the extension has no relocatable schema."""

    comment: str | None = None
    """Optional description from ``pg_description``."""

    @model_validator(mode="after")
    def _check_ref_kind(self) -> Self:
        if self.ref.kind is not ObjectKind.EXTENSION:
            raise ValueError(f"Extension.ref must have kind EXTENSION, got {self.ref.kind!r}")
        return self

    @property
    def name(self) -> str:
        """Convenience alias for ``self.ref.qname.name``."""
        return self.ref.qname.name
