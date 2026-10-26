"""Tests for the data-driven Textual chrome."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import pytest
from textual.widgets import ContentSwitcher, Label, Static, Tree

from pgschemadiff.application.diff.compare_schemas import SchemaComparisonResult
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta import DeltaSet
from pgschemadiff.domain.delta.enum import ReplaceEnumLabels
from pgschemadiff.domain.delta.table import AlterTableAttrs, CreateTable, DropTable
from pgschemadiff.domain.enum_type import EnumType
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.models import ConnectionInfo, Profile
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import Table
from pgschemadiff.presentation.composition import TuiDependencies
from pgschemadiff.presentation.tui import PgsdApp
from pgschemadiff.presentation.tui.screens.main import MainScreen
from pgschemadiff.presentation.tui.views._common import DiffRequested
from pgschemadiff.presentation.tui.widgets import Statusbar

if TYPE_CHECKING:
    from textual.message import Message

    from pgschemadiff.application.migration.ports import BundleReader, MigrationWriter
    from pgschemadiff.infrastructure.config.yaml_loader import ProfileLoader
    from pgschemadiff.presentation.composition import ExecutorFactory, InspectorScope


def _ref(kind: ObjectKind, name: str, *, schema: str = "public") -> ObjectRef:
    return ObjectRef(
        kind=kind,
        qname=QualifiedName(namespace=schema, name=name),
    )


def _table(name: str, *, schema: str = "public") -> Table:
    return Table(ref=_ref(ObjectKind.TABLE, name, schema=schema))


def _schema(
    name: str,
    *,
    tables: tuple[Table, ...] = (),
    enums: tuple[EnumType, ...] = (),
) -> Schema:
    return Schema(
        ref=ObjectRef(
            kind=ObjectKind.SCHEMA,
            qname=QualifiedName(namespace=name, name=name),
        ),
        tables=tables,
        enums=enums,
    )


def _comparison(
    *, schema_name: str = "public", table_name: str = "users"
) -> SchemaComparisonResult:
    added = _table(f"{table_name}_added", schema=schema_name)
    modified = _table(f"{table_name}_modified", schema=schema_name)
    dropped = _table(f"{table_name}_dropped", schema=schema_name)
    enum_ref = _ref(ObjectKind.ENUM, "state", schema=schema_name)
    source_enum = EnumType(ref=enum_ref, labels=("old", "pending"))
    target_enum = EnumType(ref=enum_ref, labels=("new", "pending"))
    source = Database(
        name="source_db",
        schemas=(_schema(schema_name, tables=(modified, dropped), enums=(source_enum,)),),
    )
    target = Database(
        name="target_db",
        schemas=(_schema(schema_name, tables=(added, modified), enums=(target_enum,)),),
    )
    deltas = DeltaSet.from_iterable(
        (
            CreateTable(target=added.ref, table=added),
            AlterTableAttrs(target=modified.ref, new_comment="changed"),
            DropTable(target=dropped.ref, table=dropped),
            ReplaceEnumLabels(
                target=enum_ref,
                old_labels=("old", "pending"),
                new_labels=("new", "pending"),
            ),
        )
    )
    return SchemaComparisonResult(source=source, target=target, deltas=deltas)


def _profile() -> Profile:
    return Profile(
        name="profile[a]",
        source=ConnectionInfo(
            host="source-secret.example.test",
            database="source_db",
            user="source_user",
            password="source-password-sentinel",
        ),
        target=ConnectionInfo(
            host="target-secret.example.test",
            database="target_db",
            user="target_user",
            password="target-password-sentinel",
        ),
    )


def _dependencies(
    profile: Profile,
    comparison: SchemaComparisonResult,
) -> TuiDependencies:
    profile_loader = Mock()
    profile_loader.load.return_value = [profile]
    profile_loader.config_path = Path("profiles.yaml")

    async def compare(
        _source: str,
        _target: str,
        _schemas: list[str] | None,
    ) -> SchemaComparisonResult:
        return comparison

    return TuiDependencies(
        profile_loader=cast("ProfileLoader", profile_loader),
        inspector_scope=cast("InspectorScope", Mock()),
        migration_writer=cast("MigrationWriter", Mock()),
        bundle_reader=cast("BundleReader", Mock()),
        executor_factory=cast("ExecutorFactory", Mock()),
        compare=compare,
    )


@pytest.mark.unit
async def test_chrome_mounts_explicit_empty_tree_without_dependencies() -> None:
    app = PgsdApp()

    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()

        tree = app.query_one("#schema-tree", Tree)
        empty_state = app.query_one("#tree-empty", Static)
        statusbar = app.query_one(Statusbar)

        assert len(tree.root.children) == 0
        assert "Test connections to load objects" in str(empty_state.render())
        assert "0 changes" in str(app.query_one("#sb-counts", Label).render())
        assert statusbar.selected == "—"


@pytest.mark.unit
async def test_comparison_populates_tree_header_and_status_from_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posted_diffs: list[DiffRequested] = []
    post_message = MainScreen.post_message

    def record_diff_request(screen: MainScreen, message: Message) -> bool:
        if isinstance(message, DiffRequested):
            posted_diffs.append(message)
        return post_message(screen, message)

    monkeypatch.setattr(MainScreen, "post_message", record_diff_request)
    monkeypatch.setattr(metadata, "version", lambda _package: "9.8.7")
    result = _comparison(schema_name="a[b]", table_name="things[b]")
    app = PgsdApp(dependencies=_dependencies(_profile(), result))

    async with app.run_test(size=(140, 44)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.action_test_both()
        await app.workers.wait_for_complete()
        await pilot.pause()

        tree = app.query_one("#schema-tree", Tree)
        schema_node = tree.root.children[0]
        labels = [str(node.label) for group in schema_node.children for node in group.children]
        header_version = str(app.query_one("#brand", Label).render())
        pills = str(app.query_one("#connection-pills", Label).render())
        counts = str(app.query_one("#sb-counts", Label).render())

        assert str(schema_node.label).endswith("a[b]")
        assert {str(node.label) for node in schema_node.children} >= {"▾ tables", "▾ enums"}
        assert any("things[b]_added" in label and "+" in label for label in labels)
        assert any("things[b]_modified" in label and "~" in label for label in labels)
        assert any("things[b]_dropped" in label and "-" in label for label in labels)
        assert any("state" in label and "~" in label for label in labels)
        assert "v9.8.7" in header_version
        assert "profile[a]" in pills
        assert "source_db" in pills
        assert "target_db" in pills
        assert "source-secret.example.test" not in pills
        assert "target-secret.example.test" not in pills
        assert "password-sentinel" not in pills
        assert "4 changes" in counts
        assert "1 blocked" in counts
        assert "conflict" not in counts.lower()

        added_node = next(
            node for node in schema_node.children[0].children if "_added" in str(node.label)
        )
        tree.select_node(added_node)
        await pilot.pause()
        assert "things[b]_added" in str(app.query_one("#sb-selected", Label).render())
        assert app.query_one("#content", ContentSwitcher).current == "overview"
        assert posted_diffs == []
        assert not tree.show_root
        assert isinstance(app.screen, MainScreen)


@pytest.mark.unit
async def test_mixed_create_and_drop_for_one_object_shows_modify_glyph() -> None:
    base = _comparison()
    table = _table("users_modified")
    comparison = SchemaComparisonResult(
        source=base.source,
        target=base.target,
        deltas=DeltaSet.from_iterable(
            (
                CreateTable(target=table.ref, table=table),
                DropTable(target=table.ref, table=table),
            )
        ),
    )
    app = PgsdApp(dependencies=_dependencies(_profile(), comparison))

    async with app.run_test(size=(140, 44)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.action_test_both()
        await app.workers.wait_for_complete()
        await pilot.pause()

        tree = app.query_one("#schema-tree", Tree)
        schema_node = tree.root.children[0]
        tables = next(node for node in schema_node.children if "tables" in str(node.label))
        modified_node = next(
            node for node in tables.children if "users_modified" in str(node.label)
        )

        assert "~" in str(modified_node.label)
        assert "+" not in str(modified_node.label)
        assert "-" not in str(modified_node.label)


@pytest.mark.unit
async def test_header_falls_back_to_dev_when_package_metadata_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_package(_package: str) -> str:
        raise metadata.PackageNotFoundError

    monkeypatch.setattr(metadata, "version", missing_package)
    app = PgsdApp()

    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        assert "pgschemadiff vdev" in str(app.query_one("#brand", Label).render())
