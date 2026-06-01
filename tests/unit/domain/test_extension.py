"""Unit tests for ``pgschemadiff.domain.extension`` (task P1-DOM-06)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ext_ref(name: str) -> ObjectRef:
    return ObjectRef(kind=ObjectKind.EXTENSION, qname=QualifiedName(namespace="public", name=name))


# ---------------------------------------------------------------------------
# Extension — construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extension_minimal() -> None:
    ref = _ext_ref("pgcrypto")
    ext = Extension(ref=ref, version="1.3")
    assert ext.name == "pgcrypto"
    assert ext.version == "1.3"
    assert ext.installed_schema is None
    assert ext.comment is None


@pytest.mark.unit
def test_extension_with_installed_schema() -> None:
    ref = _ext_ref("postgis")
    ext = Extension(ref=ref, version="3.4.0", installed_schema="public")
    assert ext.installed_schema == "public"


@pytest.mark.unit
def test_extension_with_comment() -> None:
    ref = _ext_ref("uuid-ossp")
    ext = Extension(ref=ref, version="1.1", comment="UUID generation functions")
    assert ext.comment == "UUID generation functions"


# ---------------------------------------------------------------------------
# Extension — validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extension_rejects_non_extension_ref() -> None:
    bad_ref = ObjectRef(kind=ObjectKind.TABLE, qname=QualifiedName(namespace="public", name="t"))
    with pytest.raises(ValidationError, match="must have kind EXTENSION"):
        Extension(ref=bad_ref, version="1.0")


@pytest.mark.unit
def test_extension_rejects_empty_version() -> None:
    ref = _ext_ref("ext")
    with pytest.raises(ValidationError):
        Extension(ref=ref, version="")


@pytest.mark.unit
def test_extension_rejects_extra_fields() -> None:
    ref = _ext_ref("ext")
    with pytest.raises(ValidationError):
        Extension(ref=ref, version="1.0", unknown=1)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Extension — immutability
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extension_is_frozen() -> None:
    ref = _ext_ref("ext")
    ext = Extension(ref=ref, version="1.0")
    with pytest.raises(ValidationError):
        ext.version = "2.0"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Extension — name property
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extension_name_property() -> None:
    ref = _ext_ref("hstore")
    ext = Extension(ref=ref, version="1.8")
    assert ext.name == "hstore"


# ---------------------------------------------------------------------------
# Extension — JSON round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extension_json_round_trip() -> None:
    ref = _ext_ref("postgis")
    ext = Extension(ref=ref, version="3.4.0", installed_schema="public", comment="PostGIS")
    restored = Extension.model_validate_json(ext.model_dump_json())
    assert restored == ext


# ---------------------------------------------------------------------------
# Extension — equality / hash
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extension_equality_and_hash() -> None:
    ref = _ext_ref("pgcrypto")
    a = Extension(ref=ref, version="1.3")
    b = Extension(ref=ref, version="1.3")
    c = Extension(ref=ref, version="1.4")
    assert a == b
    assert hash(a) == hash(b)
    assert a != c
