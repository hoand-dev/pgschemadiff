import pytest

from pgschemadiff.application.diff.comparators import ExtensionComparator
from pgschemadiff.domain.delta.schema import AlterExtension, CreateExtension, DropExtension
from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.shared.errors import DiffError


def _extension(
    *,
    version: str = "1.0",
    installed_schema: str | None = "public",
    comment: str | None = None,
) -> Extension:
    ref = ObjectRef(
        kind=ObjectKind.EXTENSION,
        qname=QualifiedName(namespace="public", name="pgcrypto"),
    )
    return Extension(
        ref=ref,
        version=version,
        installed_schema=installed_schema,
        comment=comment,
    )


def test_extension_create_returns_delta_with_target_payload() -> None:
    target = _extension(comment="cryptographic functions")

    (delta,) = ExtensionComparator().compare(None, target)

    assert isinstance(delta, CreateExtension)
    assert delta.target == target.ref
    assert delta.extension == target


def test_extension_drop_returns_delta_with_source_payload() -> None:
    source = _extension(comment="cryptographic functions")

    (delta,) = ExtensionComparator().compare(source, None)

    assert isinstance(delta, DropExtension)
    assert delta.target == source.ref
    assert delta.extension == source


def test_unchanged_extension_emits_no_delta() -> None:
    source = _extension()
    target = _extension()

    assert ExtensionComparator().compare(source, target) == ()


def test_both_missing_extensions_emit_no_delta() -> None:
    assert ExtensionComparator().compare(None, None) == ()


def test_extension_version_and_schema_changes_share_one_delta() -> None:
    source = _extension(version="1.0", installed_schema="public")
    target = _extension(version="2.0", installed_schema="extensions")

    (delta,) = ExtensionComparator().compare(source, target)

    assert isinstance(delta, AlterExtension)
    assert delta.target == target.ref
    assert delta.new_version == "2.0"
    assert delta.new_schema == "extensions"


def test_extension_schema_change_to_none_raises_diff_error() -> None:
    source = _extension(installed_schema="public")
    target = _extension(installed_schema=None)

    with pytest.raises(DiffError, match="schema"):
        ExtensionComparator().compare(source, target)


def test_extension_comment_change_raises_diff_error() -> None:
    source = _extension(comment="old comment")
    target = _extension(comment="new comment")

    with pytest.raises(DiffError, match="comment"):
        ExtensionComparator().compare(source, target)
