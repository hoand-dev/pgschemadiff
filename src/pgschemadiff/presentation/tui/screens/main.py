"""Main composite screen: header / sidebar / tab body / statusbar / cmdbar."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from rich.markup import escape
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import ContentSwitcher, Input, Static, Tree

from pgschemadiff.domain.delta.base import DeltaOp
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.presentation.tui.views import (
    ApplyView,
    ConnectionView,
    DiffView,
    HistoryView,
    MigrationView,
    OverviewView,
    SettingsView,
)
from pgschemadiff.presentation.tui.widgets import (
    Cmdbar,
    HeaderBar,
    Statusbar,
    TabSpec,
    ViewTabs,
)

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from pgschemadiff.application.diff.compare_schemas import SchemaComparisonResult
    from pgschemadiff.presentation.tui.session import TuiSession

TAB_SPECS: tuple[TabSpec, ...] = (
    TabSpec("connection", "Connection", "gc"),
    TabSpec("overview", "Overview", "go"),
    TabSpec("diff", "Diff", "gd"),
    TabSpec("migration", "Migration", "gm"),
    TabSpec("apply", "Apply", "ga"),
    TabSpec("history", "History", "gh"),
    TabSpec("settings", "Settings", "gs"),
)

_GLYPHS = {"add": "+", "mod": "~", "del": "-"}
_KIND_LABELS = {
    ObjectKind.TABLE: "tables",
    ObjectKind.VIEW: "views",
    ObjectKind.MATERIALIZED_VIEW: "materialized views",
    ObjectKind.INDEX: "indexes",
    ObjectKind.SEQUENCE: "sequences",
    ObjectKind.FUNCTION: "functions",
    ObjectKind.PROCEDURE: "procedures",
    ObjectKind.ENUM: "enums",
    ObjectKind.COMPOSITE_TYPE: "composite types",
    ObjectKind.DOMAIN_TYPE: "domain types",
    ObjectKind.COLUMN: "columns",
    ObjectKind.CONSTRAINT: "constraints",
    ObjectKind.TRIGGER: "triggers",
    ObjectKind.POLICY: "policies",
    ObjectKind.EXTENSION: "extensions",
}
_KIND_ICONS = {
    ObjectKind.SCHEMA: "◈",
    ObjectKind.TABLE: "▦",
    ObjectKind.VIEW: "◫",
    ObjectKind.MATERIALIZED_VIEW: "◫",
    ObjectKind.INDEX: "⌘",
    ObjectKind.SEQUENCE: "↕",
    ObjectKind.FUNCTION: "ƒ",
    ObjectKind.PROCEDURE: "ƒ",
    ObjectKind.ENUM: "τ",
    ObjectKind.COMPOSITE_TYPE: "τ",
    ObjectKind.DOMAIN_TYPE: "τ",
    ObjectKind.COLUMN: "·",
    ObjectKind.CONSTRAINT: "⌑",
    ObjectKind.TRIGGER: "↯",
    ObjectKind.POLICY: "♧",
    ObjectKind.EXTENSION: "⬡",
}
_SCHEMA_COLLECTIONS = (
    (ObjectKind.TABLE, "tables"),
    (ObjectKind.INDEX, "indexes"),
    (ObjectKind.ENUM, "enums"),
    (ObjectKind.COMPOSITE_TYPE, "composite_types"),
    (ObjectKind.DOMAIN_TYPE, "domain_types"),
    (ObjectKind.SEQUENCE, "sequences"),
    (ObjectKind.FUNCTION, "functions"),
    (ObjectKind.PROCEDURE, "procedures"),
    (ObjectKind.VIEW, "views"),
    (ObjectKind.MATERIALIZED_VIEW, "materialized_views"),
)


def _op_status(op: DeltaOp) -> str:
    if op is DeltaOp.CREATE:
        return "add"
    if op is DeltaOp.DROP:
        return "del"
    return "mod"


def _object_name(ref: ObjectRef) -> str:
    if ref.parent is not None:
        return f"{ref.parent.qname.name}.{ref.qname.name}"
    signature = f"({', '.join(ref.arg_signature)})" if ref.arg_signature else ""
    return f"{ref.qname.name}{signature}"


def _object_key(ref: ObjectRef) -> str:
    parent = f".{ref.parent.qname.name}" if ref.parent is not None else ""
    signature = f"({', '.join(ref.arg_signature)})" if ref.arg_signature else ""
    return f"{ref.qname.namespace}.{ref.kind.value}{parent}.{ref.qname.name}{signature}"


def _tree_label(kind: ObjectKind, name: str, status: str | None = None) -> str:
    icon = _KIND_ICONS.get(kind, "·")
    glyph = f"  {_GLYPHS[status]}" if status is not None else ""
    return f"{icon} {escape(name)}{glyph}"


def _snapshot_objects(
    comparison: SchemaComparisonResult,
) -> tuple[
    dict[str, ObjectRef],
    dict[str, dict[ObjectKind, set[ObjectRef]]],
    set[ObjectRef],
]:
    schema_refs: dict[str, ObjectRef] = {}
    schema_objects: dict[str, dict[ObjectKind, set[ObjectRef]]] = defaultdict(
        lambda: defaultdict(set)
    )
    extensions: dict[ObjectRef, str | None] = {}

    for database in (comparison.source, comparison.target):
        for schema in database.schemas:
            schema_refs[schema.name] = schema.ref
            objects = schema_objects[schema.name]
            for kind, attribute in _SCHEMA_COLLECTIONS:
                objects[kind].update(item.ref for item in getattr(schema, attribute))
            for table in schema.tables:
                for column in table.columns:
                    objects[ObjectKind.COLUMN].add(
                        ObjectRef(
                            kind=ObjectKind.COLUMN,
                            qname=QualifiedName(
                                namespace=table.ref.qname.namespace,
                                name=column.name,
                            ),
                            parent=table.ref,
                        )
                    )
                for constraint in table.constraints:
                    objects[ObjectKind.CONSTRAINT].add(
                        ObjectRef(
                            kind=ObjectKind.CONSTRAINT,
                            qname=QualifiedName(
                                namespace=table.ref.qname.namespace,
                                name=constraint.name,
                            ),
                            parent=table.ref,
                        )
                    )
                objects[ObjectKind.TRIGGER].update(trigger.ref for trigger in table.triggers)
                objects[ObjectKind.POLICY].update(policy.ref for policy in table.policies)
        for extension in database.extensions:
            extensions[extension.ref] = extension.installed_schema

    unscoped_extensions: set[ObjectRef] = set()
    for ref, schema_name in extensions.items():
        if schema_name is not None and schema_name in schema_objects:
            schema_objects[schema_name][ObjectKind.EXTENSION].add(ref)
        else:
            unscoped_extensions.add(ref)

    return schema_refs, schema_objects, unscoped_extensions


class MainScreen(Screen[None]):
    """Top-level screen — composes the entire pgsd chrome."""

    DEFAULT_CSS = """
    MainScreen { layout: vertical; }
    MainScreen > #body {
        height: 1fr;
        layout: horizontal;
    }
    MainScreen #sidebar {
        width: 36;
        background: $surface;
        border-right: solid $surface-lighten-1;
    }
    MainScreen #sidebar.hidden { display: none; }
    MainScreen #sidebar .sb-head {
        background: $surface;
        color: $text-muted;
        padding: 0 1;
        text-style: bold;
        border-bottom: solid $surface-lighten-1;
    }
    MainScreen #sidebar #sidebar-search {
        border: none;
        height: 1;
        background: $panel;
        margin: 0 1;
    }
    MainScreen #tree-empty { padding: 1; color: $text-muted; }
    MainScreen #tree-empty.hidden, MainScreen #schema-tree.hidden { display: none; }
    MainScreen #sidebar .sb-legend {
        dock: bottom;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
        border-top: solid $surface-lighten-1;
    }
    MainScreen #sidebar Tree { background: $surface; height: 1fr; }
    MainScreen #main { width: 1fr; }
    MainScreen ContentSwitcher { height: 1fr; background: $background; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._selection_labels: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="hdr")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("  SCHEMA EXPLORER", classes="sb-head")
                yield Input(placeholder="/ filter…", id="sidebar-search")
                yield Static("Test connections to load objects", id="tree-empty")
                yield Tree("schemas", id="schema-tree", classes="hidden")
                yield Static(
                    "legend: [$success]+[/] add  [$warning]~[/] modify  [$error]-[/] drop",
                    classes="sb-legend",
                )
            with Vertical(id="main"):
                yield ViewTabs(TAB_SPECS, initial="overview")
                with ContentSwitcher(initial="overview", id="content"):
                    yield ConnectionView(id="connection")
                    yield OverviewView(id="overview")
                    yield DiffView(id="diff")
                    yield MigrationView(id="migration")
                    yield ApplyView(id="apply")
                    yield HistoryView(id="history")
                    yield SettingsView(id="settings")
        yield Statusbar(id="status")
        yield Cmdbar(id="cmd")

    def update_from_session(self, session: TuiSession) -> None:
        """Refresh chrome from the current profile and comparison snapshots."""
        self.query_one(HeaderBar).update_profile(session.selected_profile)
        self.query_one(Statusbar).update_comparison(session.last_comparison)
        self.query_one("#overview", OverviewView).update_comparison(session.last_comparison)
        self.update_tree(session.last_comparison)

    def update_tree(self, comparison: SchemaComparisonResult | None) -> None:
        """Rebuild the schema/object tree from the retained comparison."""
        tree = self.query_one("#schema-tree", Tree)
        tree.clear()
        tree.show_root = False
        tree.guide_depth = 2
        self._selection_labels.clear()
        empty_state = self.query_one("#tree-empty", Static)
        tree.set_class(comparison is None, "hidden")
        empty_state.set_class(comparison is not None, "hidden")
        self.query_one(Statusbar).update_selected(None)
        if comparison is None:
            return

        schema_refs, schema_objects, unscoped_extensions = _snapshot_objects(comparison)
        status_by_ref: dict[ObjectRef, str] = {}
        for delta in comparison.deltas:
            status = _op_status(delta.op)
            existing = status_by_ref.get(delta.target)
            status_by_ref[delta.target] = (
                status if existing is None or existing == status else "mod"
            )

        for schema_name in sorted(schema_objects):
            schema_key = f"schema:{schema_name}"
            schema_ref = schema_refs[schema_name]
            schema_node = tree.root.add(
                _tree_label(ObjectKind.SCHEMA, schema_name, status_by_ref.get(schema_ref)),
                expand=True,
                data=schema_key,
            )
            self._selection_labels[schema_key] = schema_name
            for kind, group_name in _KIND_LABELS.items():
                refs = sorted(
                    schema_objects[schema_name].get(kind, set()),
                    key=_object_key,
                )
                if not refs:
                    continue
                group_key = f"group:{schema_name}:{kind.value}"
                group_node = schema_node.add(
                    f"▾ {group_name}",
                    expand=True,
                    data=group_key,
                )
                self._selection_labels[group_key] = group_name
                for ref in refs:
                    object_key = _object_key(ref)
                    selection_key = f"object:{object_key}"
                    group_node.add_leaf(
                        _tree_label(kind, _object_name(ref), status_by_ref.get(ref)),
                        data=selection_key,
                    )
                    self._selection_labels[selection_key] = _object_name(ref)

        if unscoped_extensions:
            extension_group = tree.root.add(
                "▾ extensions",
                expand=True,
                data="group:extensions",
            )
            self._selection_labels["group:extensions"] = "extensions"
            for ref in sorted(unscoped_extensions, key=_object_key):
                object_key = _object_key(ref)
                selection_key = f"object:{object_key}"
                extension_group.add_leaf(
                    _tree_label(
                        ObjectKind.EXTENSION,
                        _object_name(ref),
                        status_by_ref.get(ref),
                    ),
                    data=selection_key,
                )
                self._selection_labels[selection_key] = _object_name(ref)

    def on_tree_node_selected(self, event: Tree.NodeSelected[str]) -> None:
        selection_key = event.node.data
        self.query_one(Statusbar).update_selected(self._selection_labels.get(selection_key or ""))
