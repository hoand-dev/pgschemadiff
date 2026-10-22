import pytest

from pgschemadiff.application.diff.comparators import SchemaComparator
from pgschemadiff.domain.delta.schema import CreateSchema, DropSchema
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import Table
from pgschemadiff.shared.errors import DiffError


def _schema(*, owner: str | None = None, comment: str | None = None) -> Schema:
    ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name="public"),
    )
    return Schema(ref=ref, owner=owner, comment=comment)


def test_schema_create_returns_delta_with_target_payload() -> None:
    target = _schema(owner="app_owner", comment="application schema")

    (delta,) = SchemaComparator().compare(None, target)

    assert isinstance(delta, CreateSchema)
    assert delta.target == target.ref
    assert delta.pg_schema == target


def test_schema_drop_returns_delta_with_source_payload() -> None:
    source = _schema(owner="app_owner", comment="application schema")

    (delta,) = SchemaComparator().compare(source, None)

    assert isinstance(delta, DropSchema)
    assert delta.target == source.ref
    assert delta.pg_schema == source


def test_unchanged_schema_emits_no_delta() -> None:
    source = _schema(owner="app_owner", comment="application schema")
    target = _schema(owner="app_owner", comment="application schema")

    assert SchemaComparator().compare(source, target) == ()


def test_both_missing_schemas_emit_no_delta() -> None:
    assert SchemaComparator().compare(None, None) == ()


def test_schema_owner_change_raises_diff_error() -> None:
    source = _schema(owner="old_owner")
    target = _schema(owner="new_owner")

    with pytest.raises(DiffError, match="owner"):
        SchemaComparator().compare(source, target)


def test_schema_comment_change_raises_diff_error() -> None:
    source = _schema(comment="old comment")
    target = _schema(comment="new comment")

    with pytest.raises(DiffError, match="comment"):
        SchemaComparator().compare(source, target)


def test_schema_comparison_ignores_child_objects() -> None:
    source = _schema()
    target = source.model_copy(
        update={
            "tables": (
                Table(
                    ref=ObjectRef(
                        kind=ObjectKind.TABLE,
                        qname=QualifiedName(namespace="public", name="users"),
                    )
                ),
            )
        }
    )

    assert SchemaComparator().compare(source, target) == ()
