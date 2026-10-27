"""Tests for schema fingerprints."""

from __future__ import annotations

from pgschemadiff.application.diff.fingerprint import schema_fingerprint
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import Table


def _database(name: str = "app", *, data_type: str = "integer") -> Database:
    schema_ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name="public"),
    )
    table_ref = ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name="items"),
    )
    table = Table(
        ref=table_ref,
        columns=(Column(name="id", position=1, data_type=data_type),),
    )
    schema = Schema(ref=schema_ref, tables=(table,))
    return Database(name=name, schemas=(schema,))


def test_schema_fingerprint_is_deterministic() -> None:
    assert schema_fingerprint(_database()) == schema_fingerprint(_database())


def test_schema_fingerprint_excludes_database_name() -> None:
    assert schema_fingerprint(_database("production")) == schema_fingerprint(_database("staging"))


def test_schema_fingerprint_changes_when_column_type_changes() -> None:
    assert schema_fingerprint(_database(data_type="integer")) != schema_fingerprint(
        _database(data_type="text")
    )
