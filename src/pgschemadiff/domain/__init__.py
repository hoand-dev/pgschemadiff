"""Domain layer — pure Pydantic models. No IO, no async, no third-party drivers."""

from pgschemadiff.domain.identity import (
    SUB_OBJECT_KINDS,
    ObjectKind,
    ObjectRef,
    QualifiedName,
)

__all__ = [
    "SUB_OBJECT_KINDS",
    "ObjectKind",
    "ObjectRef",
    "QualifiedName",
]
