"""Diff view over retained schema snapshots and typed delta models."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel
from textual.containers import Horizontal, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from pgschemadiff.application.migration.generate import assess_deltas
from pgschemadiff.domain.identity import ObjectKind
from pgschemadiff.presentation.tui.views._common import (
    Panel,
    SectionHeader,
    chip,
    markup,
    op_chip,
    risk_chip,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from textual import events
    from textual.app import ComposeResult

    from pgschemadiff.application.diff.compare_schemas import SchemaComparisonResult
    from pgschemadiff.application.sql_emit.risk import RiskAssessment
    from pgschemadiff.domain.delta.base import DeltaBase
    from pgschemadiff.domain.identity import ObjectRef
    from pgschemadiff.presentation.tui.session import TuiSession

_MODES = ("side", "inline", "tree")
_DELTA_METADATA = frozenset({"op", "kind", "target"})
_CHILD_OBJECT_FIELDS = {
    ObjectKind.COLUMN: "columns",
    ObjectKind.CONSTRAINT: "constraints",
    ObjectKind.TRIGGER: "triggers",
    ObjectKind.POLICY: "policies",
}


def _value_text(value: object) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, BaseModel):
        fields = ", ".join(
            f"{name}={_value_text(getattr(value, name))}" for name in type(value).model_fields
        )
        return "{" + fields + "}"
    if isinstance(value, (tuple, list)):
        return "[" + ", ".join(_value_text(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{key}: {_value_text(item)}" for key, item in value.items()) + "}"
    if isinstance(value, str):
        return repr(value)
    return str(value)


def _nested_models(value: object) -> Iterator[BaseModel]:
    if isinstance(value, BaseModel):
        yield value
        for name in type(value).model_fields:
            yield from _nested_models(getattr(value, name))
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _nested_models(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _nested_models(item)


def _find_snapshot_object(snapshot: BaseModel, target: ObjectRef) -> BaseModel | None:
    for model in _nested_models(snapshot):
        if getattr(model, "ref", None) == target:
            return model

    if target.parent is None:
        return None
    parent = _find_snapshot_object(snapshot, target.parent)
    field_name = _CHILD_OBJECT_FIELDS.get(target.kind)
    if parent is None or field_name is None:
        return None
    for child in getattr(parent, field_name, ()):
        if not isinstance(child, BaseModel):
            continue
        if (
            getattr(child, "ref", None) == target
            or getattr(child, "name", None) == target.qname.name
        ):
            return child
    return None


def _model_fields(model: BaseModel, depth: int = 0) -> Iterator[Static]:
    for name in type(model).model_fields:
        value = getattr(model, name)
        yield from _tree_lines(name, value, depth)


def _tree_lines(label: str, value: object, depth: int) -> Iterator[Static]:
    indent = "  " * depth
    if isinstance(value, BaseModel):
        yield Static(markup("$indent$label:", indent=indent, label=label), classes="tree-line")
        yield from _model_fields(value, depth + 1)
        return
    if isinstance(value, (tuple, list)) and any(isinstance(item, BaseModel) for item in value):
        yield Static(markup("$indent$label:", indent=indent, label=label), classes="tree-line")
        for index, item in enumerate(value):
            yield from _tree_lines(f"[{index}]", item, depth + 1)
        return
    yield Static(
        markup("$indent$label: $value", indent=indent, label=label, value=_value_text(value)),
        classes="tree-line",
    )


def _inline_changes(
    delta: DeltaBase,
    source_object: BaseModel | None,
    target_object: BaseModel | None,
) -> tuple[str, ...]:
    fields = type(delta).model_fields
    names = [
        name for name in fields if name not in _DELTA_METADATA and name in delta.model_fields_set
    ]
    paired: set[str] = set()
    lines: list[str] = []
    for name in names:
        if name.startswith("old_"):
            suffix = name.removeprefix("old_")
            new_name = f"new_{suffix}"
            if new_name in names:
                lines.append(
                    f"{suffix}: {_value_text(getattr(delta, name))} → "
                    f"{_value_text(getattr(delta, new_name))}"
                )
                paired.update({name, new_name})
    for name in names:
        if name in paired:
            continue
        value = getattr(delta, name)
        if name.startswith("new_"):
            field_name = name.removeprefix("new_")
            if (
                source_object is not None
                and target_object is not None
                and hasattr(source_object, field_name)
                and hasattr(target_object, field_name)
                and getattr(target_object, field_name) == value
            ):
                lines.append(
                    f"{field_name}: {_value_text(getattr(source_object, field_name))} → "
                    f"{_value_text(value)}"
                )
                continue
            lines.append(f"+ {field_name}: {_value_text(value)}")
        elif name.startswith("old_"):
            lines.append(f"- {name.removeprefix('old_')}: {_value_text(value)}")
        else:
            sign = "-" if delta.op.value == "drop" else "+"
            lines.append(f"{sign} {name}: {_value_text(value)}")
    return tuple(lines)


class DiffView(Widget):
    """Inspect one assessed delta against the retained source and target snapshots."""

    comparison: reactive[SchemaComparisonResult | None] = reactive(None, recompose=True)
    delta_id: reactive[str] = reactive("", recompose=True)
    mode: reactive[str] = reactive("side", recompose=True)
    profile_name: reactive[str] = reactive("", recompose=True)

    DEFAULT_CSS = """
    DiffView { height: 1fr; }
    DiffView > VerticalScroll { height: 1fr; padding: 1 2; }
    DiffView .toolbar { height: 1; margin-bottom: 1; }
    DiffView .mode-pills { width: 29; }
    DiffView .pill {
        width: 9;
        content-align: center middle;
        color: $text-muted;
        background: $boost;
        margin-right: 1;
    }
    DiffView .pill.active { background: $primary; color: $background; text-style: bold; }
    DiffView .nav { padding: 0 1; margin-left: 1; background: $boost; color: $text; }
    DiffView .jumps { height: auto; margin-bottom: 1; }
    DiffView .chip { padding: 0 1; margin-right: 1; background: $boost; color: $text-muted; }
    DiffView .chip.active { background: $primary; color: $background; text-style: bold; }
    DiffView .jumps > Static { width: auto; }
    DiffView .summary { height: auto; margin-bottom: 1; }
    DiffView .reason { height: auto; margin-bottom: 1; }
    DiffView .sides { height: auto; }
    DiffView .side { width: 1fr; }
    DiffView .side.left { margin-right: 1; }
    DiffView .side-head { text-style: bold; padding: 0 1; }
    DiffView .side-head.src { color: $secondary; }
    DiffView .side-head.tgt { color: $warning; }
    DiffView .diff-line { padding: 0 1; height: auto; }
    DiffView .diff-add { color: $success; }
    DiffView .diff-del { color: $error; }
    DiffView .tree-line { height: auto; }
    """

    def update_from_session(self, session: TuiSession) -> None:
        """Refresh the view from the current session comparison and profile."""
        self.comparison = session.last_comparison
        self.profile_name = (
            session.selected_profile.name if session.selected_profile is not None else ""
        )

    def _assessed(self) -> tuple[tuple[str, RiskAssessment], ...]:
        if self.comparison is None:
            return ()
        return assess_deltas(self.comparison.deltas)

    def compose(self) -> ComposeResult:
        comparison = self.comparison
        if comparison is None:
            yield SectionHeader("Diff")
            yield Static("No comparison available. Compare schemas to inspect a delta.")
            return

        assessed = self._assessed()
        selected = next(
            (
                (delta_id, assessment)
                for delta_id, assessment in assessed
                if delta_id == self.delta_id
            ),
            None,
        )
        if selected is None:
            yield SectionHeader("Diff")
            if self.delta_id:
                yield Static(markup("Unknown delta ID: $delta_id", delta_id=self.delta_id))
            else:
                yield Static("Select a changed object from Overview.")
            return

        _delta_id, assessment = selected
        delta = assessment.delta
        target = delta.target
        source_object = _find_snapshot_object(comparison.source, target)
        target_object = _find_snapshot_object(comparison.target, target)
        qualified_name = _qualified_name(target)
        profile = self.profile_name or "profile"
        crumb = (
            f"{profile} · {comparison.source.name} → {comparison.target.name} · {target.kind.value}"
        )

        yield SectionHeader(f"Diff: {qualified_name}", crumb)
        with VerticalScroll():
            summary = (
                op_chip(delta.op.name)
                .append(" ")
                .append(chip(target.kind.value))
                .append(" ")
                .append(risk_chip(assessment.level.value))
            )
            yield Static(summary, classes="summary")
            yield Static(markup("Risk reason: $reason", reason=assessment.reason), classes="reason")
            with Horizontal(classes="toolbar"), Horizontal(classes="mode-pills"):
                for mode in _MODES:
                    classes = "pill active" if mode == self.mode else "pill"
                    yield Static(mode, classes=classes, id=f"mode-{mode}")
            with Horizontal(classes="jumps"):
                yield Static("jump:")
                yield Static("← previous", classes="nav", id="nav-previous")
                yield Static("next →", classes="nav", id="nav-next")
                for index, (candidate_id, _candidate) in enumerate(assessed):
                    classes = "chip active" if candidate_id == self.delta_id else "chip"
                    yield Static(
                        markup("$delta_id", delta_id=candidate_id),
                        classes=f"{classes} jump-chip",
                        id=f"jump-{index}",
                    )
            if self.mode == "inline":
                yield from self._inline(delta, source_object, target_object)
            elif self.mode == "tree":
                yield from self._tree(delta, source_object, target_object)
            else:
                yield from self._side(comparison, source_object, target_object)
            with Panel("Forward SQL"):
                yield Static("Generate a plan to preview SQL")
            with Panel("Rollback SQL"):
                yield Static("Rollback SQL is not generated")

    def _side(
        self,
        comparison: SchemaComparisonResult,
        source_object: BaseModel | None,
        target_object: BaseModel | None,
    ) -> ComposeResult:
        with Horizontal(classes="sides"):
            with VerticalScroll(classes="side left"):
                yield Static(
                    markup("SOURCE · $database · definitions", database=comparison.source.name),
                    classes="side-head src",
                )
                yield from self._definition(source_object)
            with VerticalScroll(classes="side"):
                yield Static(
                    markup("TARGET · $database · definitions", database=comparison.target.name),
                    classes="side-head tgt",
                )
                yield from self._definition(target_object)

    @staticmethod
    def _definition(model: BaseModel | None) -> ComposeResult:
        if model is None:
            yield Static("absent", classes="diff-line")
            return
        yield Static(markup("$model:", model=type(model).__name__), classes="diff-line")
        yield from _model_fields(model, 1)

    def _inline(
        self,
        delta: DeltaBase,
        source_object: BaseModel | None,
        target_object: BaseModel | None,
    ) -> ComposeResult:
        with Panel("Inline changes", subtitle="typed delta fields"):
            lines = _inline_changes(delta, source_object, target_object)
            if not lines:
                yield Static("No payload fields on this delta.", classes="diff-line")
            for line in lines:
                if line.startswith("+ "):
                    content = markup("[$success]$line[/]", line=line)
                    classes = "diff-line diff-add"
                elif line.startswith("- "):
                    content = markup("[$error]$line[/]", line=line)
                    classes = "diff-line diff-del"
                else:
                    content = markup("[$text]$line[/]", line=line)
                    classes = "diff-line"
                yield Static(content, classes=classes)

    def _tree(
        self,
        delta: BaseModel,
        source_object: BaseModel | None,
        target_object: BaseModel | None,
    ) -> ComposeResult:
        with Panel("Tree", subtitle="nested model fields"):
            yield from _tree_lines("delta", delta, 0)
            if source_object is not None:
                yield from _tree_lines("before definition", source_object, 0)
            if target_object is not None:
                yield from _tree_lines("after definition", target_object, 0)

    @staticmethod
    def _index(assessed: tuple[tuple[str, RiskAssessment], ...], delta_id: str) -> int | None:
        return next((index for index, item in enumerate(assessed) if item[0] == delta_id), None)

    def on_click(self, event: events.Click) -> None:
        widget_id = getattr(event.widget, "id", None) or ""
        if widget_id.startswith("mode-"):
            self.mode = widget_id.removeprefix("mode-")
            return

        assessed = self._assessed()
        if widget_id.startswith("jump-"):
            try:
                index = int(widget_id.removeprefix("jump-"))
                self.delta_id = assessed[index][0]
            except (IndexError, ValueError):
                return
            return

        current_index = self._index(assessed, self.delta_id)
        if current_index is None:
            return
        if widget_id == "nav-previous" and current_index > 0:
            self.delta_id = assessed[current_index - 1][0]
        elif widget_id == "nav-next" and current_index + 1 < len(assessed):
            self.delta_id = assessed[current_index + 1][0]


def _qualified_name(target: ObjectRef) -> str:
    if target.parent is not None:
        return f"{target.parent.qname.fqn}.{target.qname.name}"
    signature = f"({', '.join(target.arg_signature)})" if target.arg_signature else ""
    return f"{target.qname.fqn}{signature}"
