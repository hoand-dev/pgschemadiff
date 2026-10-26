"""Tests for the data-driven Textual chrome."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import pytest
from rich.text import Text
from textual.content import Content
from textual.geometry import Region
from textual.widgets import ContentSwitcher, Label, Static, Tree

import pgschemadiff.application.migration.generate as migration_generator
import pgschemadiff.presentation.tui.views.overview as overview_module
from pgschemadiff.application.diff.compare_schemas import SchemaComparisonResult
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta import DeltaOp, DeltaSet
from pgschemadiff.domain.delta.column import AlterColumnType
from pgschemadiff.domain.delta.enum import ReplaceEnumLabels
from pgschemadiff.domain.delta.materialized_view import ReplaceMaterializedView
from pgschemadiff.domain.delta.table import AlterTableAttrs, CreateTable, DropTable
from pgschemadiff.domain.delta.view import ReplaceView
from pgschemadiff.domain.enum_type import EnumType
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.materialized_view import MaterializedView
from pgschemadiff.domain.models import ConnectionInfo, Profile
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import Table
from pgschemadiff.domain.view import View
from pgschemadiff.presentation.composition import TuiDependencies
from pgschemadiff.presentation.tui import PgsdApp
from pgschemadiff.presentation.tui.screens.main import MainScreen
from pgschemadiff.presentation.tui.views._common import DiffRequested, SectionHeader
from pgschemadiff.presentation.tui.views.diff import DiffView
from pgschemadiff.presentation.tui.views.overview import OverviewView, _object_name
from pgschemadiff.presentation.tui.widgets import Cmdbar, HeaderBar, Statusbar

if TYPE_CHECKING:
    from textual.message import Message
    from textual.pilot import Pilot

    from pgschemadiff.application.migration.ports import BundleReader, MigrationWriter
    from pgschemadiff.domain.delta.base import DeltaBase
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
        _current: str,
        _desired: str,
        _schemas: list[str] | None,
    ) -> SchemaComparisonResult:
        # The app compares current=profile target with desired=profile source
        # and stores snapshots by profile role; return the fixture in compare
        # orientation so the session holds it unchanged.
        return SchemaComparisonResult(
            source=comparison.target,
            target=comparison.source,
            deltas=comparison.deltas,
        )

    return TuiDependencies(
        profile_loader=cast("ProfileLoader", profile_loader),
        inspector_scope=cast("InspectorScope", Mock()),
        migration_writer=cast("MigrationWriter", Mock()),
        bundle_reader=cast("BundleReader", Mock()),
        executor_factory=cast("ExecutorFactory", Mock()),
        compare=compare,
    )


def _contextual_comparison() -> SchemaComparisonResult:
    materialized_ref = _ref(ObjectKind.MATERIALIZED_VIEW, "daily_summary")
    dependent_ref = _ref(ObjectKind.VIEW, "summary_view")
    old_dependent = View(
        ref=dependent_ref,
        columns=(("day", "date"),),
        definition="SELECT day FROM public.daily_summary",
        prerequisites=(materialized_ref,),
    )
    new_dependent = View(
        ref=dependent_ref,
        columns=(("day", "date"),),
        definition="SELECT CURRENT_DATE AS day",
    )
    dependent_delta = ReplaceView(
        target=dependent_ref,
        old_view=old_dependent,
        new_view=new_dependent,
    )
    old_materialized = MaterializedView(
        ref=materialized_ref,
        columns=(("day", "date"),),
        definition="SELECT CURRENT_DATE AS day",
        dependents=(dependent_ref,),
    )
    new_materialized = MaterializedView(
        ref=materialized_ref,
        columns=(("day", "date"),),
        definition="SELECT CURRENT_DATE + 1 AS day",
    )
    materialized_delta = ReplaceMaterializedView(
        target=materialized_ref,
        old_materialized_view=old_materialized,
        new_materialized_view=new_materialized,
    )
    return SchemaComparisonResult(
        source=Database(name="source_db"),
        target=Database(name="target_db"),
        deltas=DeltaSet.from_iterable((materialized_delta, dependent_delta)),
    )


def _single_table_comparison(
    operation: str,
    *,
    schema_name: str = "public",
    table_name: str = "users",
) -> SchemaComparisonResult:
    ref = _ref(ObjectKind.TABLE, table_name, schema=schema_name)
    column = Column(name="id", position=1, data_type="integer", nullable=False)
    before = Table(ref=ref, columns=(column,), comment="before")
    after = Table(ref=ref, columns=(column,), comment="after")
    delta: DeltaBase
    source_tables: tuple[Table, ...]
    target_tables: tuple[Table, ...]

    if operation == "create":
        delta = CreateTable(target=ref, table=after)
        source_tables = ()
        target_tables = (after,)
    elif operation == "drop":
        delta = DropTable(target=ref, table=before)
        source_tables = (before,)
        target_tables = ()
    else:
        delta = AlterTableAttrs(target=ref, new_comment="after")
        source_tables = (before,)
        target_tables = (after,)

    return SchemaComparisonResult(
        source=Database(name="source_db", schemas=(_schema(schema_name, tables=source_tables),)),
        target=Database(name="target_db", schemas=(_schema(schema_name, tables=target_tables),)),
        deltas=DeltaSet.from_iterable((delta,)),
    )


def _column_comparison() -> SchemaComparisonResult:
    table_ref = _ref(ObjectKind.TABLE, "users")
    column_ref = ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace="public", name="id"),
        parent=table_ref,
    )
    old_column = Column(name="id", position=1, data_type="integer", nullable=False)
    new_column = Column(name="id", position=1, data_type="bigint", nullable=False)
    old_table = Table(ref=table_ref, columns=(old_column,))
    new_table = Table(ref=table_ref, columns=(new_column,))
    return SchemaComparisonResult(
        source=Database(name="source_db", schemas=(_schema("public", tables=(old_table,)),)),
        target=Database(name="target_db", schemas=(_schema("public", tables=(new_table,)),)),
        deltas=DeltaSet.from_iterable(
            (AlterColumnType(target=column_ref, new_data_type="bigint"),)
        ),
    )


def _untrusted_comparison(value: str) -> SchemaComparisonResult:
    table = Table(
        ref=_ref(ObjectKind.TABLE, value, schema=value),
        columns=(Column(name="id", position=1, data_type="integer", nullable=False),),
        comment=value,
    )
    schema = _schema(value, tables=(table,))
    return SchemaComparisonResult(
        source=Database(name=value, schemas=(schema,)),
        target=Database(name=value, schemas=(schema,)),
        deltas=DeltaSet.from_iterable((AlterTableAttrs(target=table.ref, new_comment=value),)),
    )


def _plain(widget: Static | Label) -> str:
    rendered = widget.render()
    return rendered.plain if isinstance(rendered, (Text, Content)) else str(rendered)


def _label_text(label: object) -> str:
    return label.plain if isinstance(label, (Content, Text)) else str(label)


def _diff_text(view: DiffView) -> str:
    return "\n".join(_plain(widget) for widget in view.query(Static))


async def _open_diff(app: PgsdApp, pilot: Pilot[None], delta_id: str = "d0001") -> DiffView:
    await app.workers.wait_for_complete()
    await pilot.pause()
    app.action_test_both()
    await app.workers.wait_for_complete()
    await pilot.pause()
    await pilot.click(f"#change-{delta_id}")
    await pilot.pause()
    return app.query_one("#diff", DiffView)


def _assert_diff_summary(view: DiffView, operation: str, result: SchemaComparisonResult) -> None:
    text = _diff_text(view)
    assessment = migration_generator.assess_deltas(result.deltas)[0][1]
    assert "profile[a]" in text
    assert '"public"."users"' in text
    assert "table" in text
    assert operation.upper() in text
    assert assessment.level.value in text
    assert assessment.reason in text


def _assert_side_mode(view: DiffView, operation: str) -> None:
    text = _diff_text(view)
    assert "definitions" in text
    assert "SOURCE" in text
    assert "TARGET" in text
    if operation == "create":
        assert "SOURCE · source_db · definitions" in text
        assert "absent" in text
        assert "after" in text
    elif operation == "drop":
        assert "TARGET · target_db · definitions" in text
        assert "absent" in text
        assert "before" in text
    else:
        assert "before" in text
        assert "after" in text


def _assert_inline_mode(view: DiffView, operation: str) -> None:
    text = _diff_text(view)
    if operation == "create":
        assert "+ table:" in text
    elif operation == "drop":
        assert "- table:" in text
    else:
        assert "comment: 'before' → 'after'" in text


def _assert_tree_mode(view: DiffView) -> None:
    text = _diff_text(view)
    assert "ref:" in text
    assert "namespace:" in text
    assert "columns:" in text
    assert "[0]:" in text
    assert "Generate a plan to preview SQL" in text
    assert "Rollback SQL is not generated" in text
    assert "tested" not in text.lower()


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
        labels = [
            _label_text(node.label) for group in schema_node.children for node in group.children
        ]
        header_version = _plain(app.query_one("#brand", Label))
        pills = _plain(app.query_one("#connection-pills", Label))
        counts = _plain(app.query_one("#sb-counts", Label))

        assert _label_text(schema_node.label).endswith("a[b]")
        assert {_label_text(node.label) for node in schema_node.children} >= {
            "▾ tables",
            "▾ enums",
        }
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
        assert "things[b]_added" in _plain(app.query_one("#sb-selected", Label))
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
        tables = next(node for node in schema_node.children if "tables" in _label_text(node.label))
        modified_node = next(
            node for node in tables.children if "users_modified" in _label_text(node.label)
        )

        assert "~" in _label_text(modified_node.label)
        assert "+" not in _label_text(modified_node.label)
        assert "-" not in _label_text(modified_node.label)


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


@pytest.mark.unit
async def test_overview_without_comparison_shows_explicit_empty_state() -> None:
    app = PgsdApp()

    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()

        empty_state = app.query_one("#overview-empty", Static)
        assert "No comparison" in _plain(empty_state)


@pytest.mark.unit
def test_overview_stat_mapping_covers_every_delta_operation() -> None:
    assert getattr(overview_module, "STAT_CARD_BY_OP", None) == {
        DeltaOp.CREATE: "added",
        DeltaOp.ALTER: "modified",
        DeltaOp.RENAME: "modified",
        DeltaOp.REPLACE: "modified",
        DeltaOp.DROP: "dropped",
    }


@pytest.mark.unit
def test_overview_object_labels_include_parent_and_routine_signature() -> None:
    table_ref = _ref(ObjectKind.TABLE, "users")
    column_ref = ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace="public", name="user_id"),
        parent=table_ref,
    )
    function_ref = ObjectRef(
        kind=ObjectKind.FUNCTION,
        qname=QualifiedName(namespace="public", name="find_user"),
        arg_signature=("integer", "text"),
    )

    assert _object_name(column_ref) == "users.user_id"
    assert _object_name(function_ref) == "find_user(integer, text)"


@pytest.mark.unit
async def test_overview_renders_ordered_real_deltas_and_op_counts() -> None:
    result = _comparison(schema_name="a[b]", table_name="things[b]")
    app = PgsdApp(dependencies=_dependencies(_profile(), result))

    async with app.run_test(size=(140, 44)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.action_test_both()
        await app.workers.wait_for_complete()
        await pilot.pause()

        overview = app.query_one("#overview", OverviewView)
        assert callable(getattr(migration_generator, "assess_deltas", None))
        expected_ids = tuple(
            delta_id for delta_id, _assessment in migration_generator.assess_deltas(result.deltas)
        )
        expected_assessments = migration_generator.assess_deltas(result.deltas)
        rows = [row for row in overview.query(".change-row") if isinstance(row, Static)]
        assert tuple(str(row.id).removeprefix("change-") for row in rows) == expected_ids
        header = _plain(overview.query_one(".change-head", Static))
        assert all(
            label in header
            for label in ("delta ID", "op", "kind", "schema", "object", "risk", "reason")
        )
        for row, (delta_id, assessment) in zip(rows, expected_assessments, strict=True):
            rendered = _plain(row)
            assert delta_id in rendered
            assert assessment.delta.target.qname.namespace in rendered
            assert assessment.delta.target.qname.name in rendered
            assert assessment.level.value in rendered
            assert assessment.reason in rendered
        assert "+1" in _plain(overview.query_one("#stat-added", Static))
        assert "~2" in _plain(overview.query_one("#stat-modified", Static))
        assert "-1" in _plain(overview.query_one("#stat-dropped", Static))
        assert "!1" in _plain(overview.query_one("#stat-blocked", Static))
        assert any("things[b]_added" in _plain(row) for row in rows)
        assert any("a[b]" in _plain(row) for row in rows)
        assert "AI review" not in "\n".join(_plain(widget) for widget in overview.query(Static))
        assert "Dependency graph" not in "\n".join(
            _plain(widget) for widget in overview.query(Static)
        )

        await pilot.click(f"#change-{expected_ids[0]}")
        await pilot.pause()
        assert app.query_one("#diff", DiffView).delta_id == expected_ids[0]


@pytest.mark.unit
async def test_overview_and_statusbar_use_contextual_view_dependency_risk() -> None:
    result = _contextual_comparison()
    app = PgsdApp(dependencies=_dependencies(_profile(), result))

    async with app.run_test(size=(140, 44)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.action_test_both()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assessments = migration_generator.assess_deltas(result.deltas)
        materialized = next(
            (delta_id, assessment)
            for delta_id, assessment in assessments
            if isinstance(assessment.delta, ReplaceMaterializedView)
        )
        assert materialized[1].level.value == "dangerous"
        assert app.query_one(Statusbar).blocked_count == 0
        assert "2 changes" in _plain(app.query_one("#sb-counts", Label))
        row = app.query_one(f"#change-{materialized[0]}", Static)
        assert "dangerous" in _plain(row)


@pytest.mark.unit
@pytest.mark.parametrize("operation", ["create", "drop", "alter"])
async def test_diff_modes_render_typed_delta_and_retained_definitions(operation: str) -> None:
    result = _single_table_comparison(operation)
    app = PgsdApp(dependencies=_dependencies(_profile(), result))

    async with app.run_test(size=(140, 44)) as pilot:
        diff = await _open_diff(app, pilot)
        _assert_diff_summary(diff, operation, result)
        await pilot.click("#mode-side")
        await pilot.pause()
        _assert_side_mode(diff, operation)
        await pilot.click("#mode-inline")
        await pilot.pause()
        _assert_inline_mode(diff, operation)
        await pilot.click("#mode-tree")
        await pilot.pause()
        _assert_tree_mode(diff)


@pytest.mark.unit
async def test_diff_navigation_uses_assessment_order() -> None:
    result = _comparison()
    expected_ids = tuple(
        delta_id for delta_id, _ in migration_generator.assess_deltas(result.deltas)
    )
    app = PgsdApp(dependencies=_dependencies(_profile(), result))

    async with app.run_test(size=(140, 44)) as pilot:
        diff = await _open_diff(app, pilot, expected_ids[0])
        assert [
            _plain(widget).strip()
            for widget in diff.query(".jump-chip")
            if isinstance(widget, Static)
        ] == list(expected_ids)

        await pilot.click("#nav-next")
        await pilot.pause()
        assert diff.delta_id == expected_ids[1]
        await pilot.click("#nav-previous")
        await pilot.pause()
        assert diff.delta_id == expected_ids[0]
        await pilot.click("#nav-previous")
        await pilot.pause()
        assert diff.delta_id == expected_ids[0]
        await pilot.click(f"#jump-{len(expected_ids) - 1}")
        await pilot.pause()
        assert diff.delta_id == expected_ids[-1]
        await pilot.click("#nav-next")
        await pilot.pause()
        assert diff.delta_id == expected_ids[-1]


@pytest.mark.unit
async def test_diff_inline_pairs_old_and_new_typed_delta_fields() -> None:
    result = _comparison()
    delta_id = next(
        delta_id
        for delta_id, assessment in migration_generator.assess_deltas(result.deltas)
        if isinstance(assessment.delta, ReplaceEnumLabels)
    )
    app = PgsdApp(dependencies=_dependencies(_profile(), result))

    async with app.run_test(size=(140, 44)) as pilot:
        diff = await _open_diff(app, pilot, delta_id)
        await pilot.click("#mode-inline")
        await pilot.pause()
        assert "labels: ['old', 'pending'] → ['new', 'pending']" in _diff_text(diff)


@pytest.mark.unit
async def test_diff_finds_nested_object_by_target_ref() -> None:
    result = _column_comparison()
    app = PgsdApp(dependencies=_dependencies(_profile(), result))

    async with app.run_test(size=(140, 44)) as pilot:
        diff = await _open_diff(app, pilot)
        side = _diff_text(diff)
        assert "SOURCE · source_db · definitions" in side
        assert "TARGET · target_db · definitions" in side
        assert "data_type: 'integer'" in side
        assert "data_type: 'bigint'" in side

        await pilot.click("#mode-inline")
        await pilot.pause()
        assert "data_type: 'integer' → 'bigint'" in _diff_text(diff)

        await pilot.click("#mode-tree")
        await pilot.pause()
        tree = _diff_text(diff)
        assert "data_type: 'integer'" in tree
        assert "data_type: 'bigint'" in tree


@pytest.mark.unit
async def test_diff_missing_comparison_and_unknown_delta_are_explicit() -> None:
    app = PgsdApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        diff = app.query_one("#diff", DiffView)
        assert "No comparison available" in _diff_text(diff)

    result = _single_table_comparison("create")
    app = PgsdApp(dependencies=_dependencies(_profile(), result))
    async with app.run_test(size=(140, 44)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.action_test_both()
        await app.workers.wait_for_complete()
        await pilot.pause()

        diff = app.query_one("#diff", DiffView)
        diff.delta_id = "d9999"
        await pilot.pause()
        assert "Unknown delta ID: d9999" in _diff_text(diff)


@pytest.mark.unit
async def test_diff_markup_like_names_are_rendered_literally() -> None:
    result = _single_table_comparison("create", schema_name="a[b]", table_name="things[b]_added")
    app = PgsdApp(dependencies=_dependencies(_profile(), result))

    async with app.run_test(size=(140, 44)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.action_test_both()
        await app.workers.wait_for_complete()
        await pilot.pause()

        await pilot.click("#change-d0001")
        await pilot.pause()
        text = _diff_text(app.query_one("#diff", DiffView))
        assert "a[b]" in text
        assert "things[b]_added" in text


@pytest.mark.unit
async def test_diff_exposes_no_accept_skip_or_ai_actions() -> None:
    result = _single_table_comparison("create")
    app = PgsdApp(dependencies=_dependencies(_profile(), result))

    async with app.run_test(size=(140, 44)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.action_test_both()
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.click("#change-d0001")
        await pilot.pause()

        diff = app.query_one("#diff", DiffView)
        text = _diff_text(diff).lower()
        assert "accept" not in text
        assert "skip" not in text
        assert "ai suggest" not in text

        await pilot.press("space", "i", "space", "a", "space", "s")
        await pilot.pause()
        assert isinstance(app.screen, MainScreen)
        assert app._active_view == "diff"
        assert "accepted" not in app.query_one(Cmdbar).hint
        assert "skipped" not in app.query_one(Cmdbar).hint


@pytest.mark.unit
async def test_header_tree_and_statusbar_render_untrusted_values_literally() -> None:
    values = ("C:\\", "[bold]x[/]", "$primary")
    app = PgsdApp(dependencies=_dependencies(_profile(), _untrusted_comparison("initial")))

    async with app.run_test(size=(140, 44)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        screen = cast("MainScreen", app.screen)
        header = app.query_one(HeaderBar)
        statusbar = app.query_one(Statusbar)
        tree = app.query_one("#schema-tree", Tree)

        for value in values:
            base_profile = _profile()
            selected_profile = base_profile.model_copy(
                update={
                    "name": value,
                    "source": base_profile.source.model_copy(update={"database": value}),
                    "target": base_profile.target.model_copy(update={"database": value}),
                }
            )
            header.update_profile(selected_profile)
            comparison = _untrusted_comparison(value)
            screen.update_tree(comparison)
            statusbar.update_comparison(comparison)
            statusbar.update_selected(value)
            await pilot.pause()

            pills = _plain(app.query_one("#connection-pills", Label))
            assert pills.count(value) >= 3
            assert "tgt →" in pills
            if value == "C:\\":
                assert "C:\\[/b]" not in pills

            schema_node = tree.root.children[0]
            assert _label_text(schema_node.label).endswith(value)
            table_group = next(
                node for node in schema_node.children if "tables" in _label_text(node.label)
            )
            assert value in _label_text(table_group.children[0].label)
            assert "1 changes" in _plain(app.query_one("#sb-counts", Label))
            assert _plain(app.query_one("#sb-selected", Label)) == value


@pytest.mark.unit
async def test_overview_and_diff_render_untrusted_values_and_following_text() -> None:
    values = ("C:\\", "[bold]x[/]", "$primary")
    app = PgsdApp(dependencies=_dependencies(_profile(), _untrusted_comparison("initial")))

    async with app.run_test(size=(140, 44)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        screen = cast("MainScreen", app.screen)
        overview = app.query_one("#overview", OverviewView)
        diff = app.query_one("#diff", DiffView)

        for value in values:
            comparison = _untrusted_comparison(value)
            selected_profile = _profile().model_copy(update={"name": value})
            app.session.select_profile(selected_profile)
            app.session.last_comparison = comparison
            screen.update_from_session(app.session)
            diff.delta_id = "d0001"
            await pilot.pause()

            overview_row = overview.query_one(".change-row", Static)
            row_text = _plain(overview_row)
            assessment = migration_generator.assess_deltas(comparison.deltas)[0][1]
            assert value in row_text
            assert assessment.reason in row_text
            assert "reason" in _plain(overview.query_one(".change-head", Static))

            diff_text = _diff_text(diff)
            assert value in diff_text
            assert assessment.reason in diff_text
            assert "Generate a plan to preview SQL" in diff_text

            diff.mode = "inline"
            await pilot.pause()
            assert value in _diff_text(diff)
            assert "Risk reason:" in _diff_text(diff)

            diff.mode = "tree"
            await pilot.pause()
            assert value in _diff_text(diff)
            assert "before definition" in _diff_text(diff)

            diff.mode = "side"
            diff.delta_id = value
            await pilot.pause()
            assert f"Unknown delta ID: {value}" in _diff_text(diff)


@pytest.mark.unit
async def test_section_header_treats_title_and_crumb_as_literal_text() -> None:
    app = PgsdApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        section = SectionHeader("C:\\", "[bold]x[/] $primary tail")
        await app.screen.mount(section)
        await pilot.pause()

        assert _plain(section) == "C:\\   [bold]x[/] $primary tail"
        lines = section.render_lines(Region(0, 0, section.size.width, section.size.height))
        assert any(
            segment.style is not None and segment.style.bold and segment.style.color is not None
            for line in lines
            for segment in line
        )
