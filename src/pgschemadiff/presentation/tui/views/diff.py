"""Diff view (``gd``) — side-by-side / inline / tree SQL diff for one object."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Horizontal, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from pgschemadiff.presentation.tui._mock import DIFFS, DiffLine, ObjectDiff
from pgschemadiff.presentation.tui.views._common import (
    AiRequested,
    Panel,
    SectionHeader,
    sql_markup,
)

if TYPE_CHECKING:
    from textual import events
    from textual.app import ComposeResult

_MODES = ("side", "inline", "tree")
_DEFAULT_KEY = "public.tenants"


def _diff_line(ln: str, sig: str, text: str, *, sig_colour: str = "$text-muted") -> str:
    num = f"[$text-muted dim]{ln:>3}[/]" if ln else "   "
    return f"{num} [{sig_colour}]{sig}[/] {sql_markup(text)}"


class DiffView(Widget):
    """Per-object SQL diff with three view modes and forward/rollback DDL."""

    object_key: reactive[str] = reactive(_DEFAULT_KEY, recompose=True)
    mode: reactive[str] = reactive("side", recompose=True)

    DEFAULT_CSS = """
    DiffView { height: 1fr; }
    DiffView > VerticalScroll { height: 1fr; padding: 1 2; }
    DiffView .toolbar { height: 1; margin-bottom: 1; }
    DiffView .pill {
        width: 9;
        content-align: center middle;
        color: $text-muted;
        background: $boost;
        margin-right: 1;
    }
    DiffView .pill.active { background: $primary; color: $background; text-style: bold; }
    DiffView .action { padding: 0 1; margin-left: 1; background: $boost; color: $text; }
    DiffView .action.accept { color: $success; }
    DiffView .action:hover { background: $surface-lighten-1; }
    DiffView .jumps { height: auto; margin-bottom: 1; }
    DiffView .chip { padding: 0 1; margin-right: 1; background: $boost; color: $text-muted; }
    DiffView .chip.active { background: $primary; color: $background; text-style: bold; }
    DiffView .conflict-flag { color: $warning; padding: 0 1; }
    DiffView .sides { height: auto; }
    DiffView .side { width: 1fr; }
    DiffView .side.left { margin-right: 1; }
    DiffView .side-head { text-style: bold; padding: 0 1; }
    DiffView .side-head.src { color: $secondary; }
    DiffView .side-head.tgt { color: $warning; }
    DiffView .diff-add { background: $success 12%; }
    DiffView .diff-del { background: $error 12%; }
    DiffView .diff-line { padding: 0 1; height: 1; }
    """

    def compose(self) -> ComposeResult:
        obj = DIFFS.get(self.object_key) or DIFFS[_DEFAULT_KEY]
        crumb = f"acme_prod → acme_staging · {obj.kind} · {obj.summary}"
        yield SectionHeader(f"Diff: {obj.title}", crumb)
        with VerticalScroll():
            with Horizontal(classes="toolbar"):
                for m in _MODES:
                    cls = "pill active" if m == self.mode else "pill"
                    yield Static(m, classes=cls, id=f"mode-{m}")
                yield Static("⌘a AI suggest", classes="action", id="act-ai")
                yield Static("␣a accept", classes="action accept", id="act-accept")
                yield Static("␣s skip", classes="action", id="act-skip")
            with Horizontal(classes="jumps"):
                yield Static("jump:", classes="conflict-flag")
                for i, key in enumerate(DIFFS):
                    cls = "chip active" if key == self.object_key else "chip"
                    yield Static(key, classes=cls, id=f"jump-{i}")
                if obj.conflict:
                    yield Static("⚠ conflict — needs resolution", classes="conflict-flag")
            yield from self._body(obj)
            with Panel("Forward migration · DDL", subtitle="copy · run :apply"):
                for line in obj.forward:
                    yield Static(_diff_line("", " ", line), classes="diff-line")
            if obj.backward:
                with Panel("Rollback · auto-generated", subtitle="tested ✓"):
                    for line in obj.backward:
                        yield Static(_diff_line("", " ", line), classes="diff-line")

    # ------------------------------------------------------------- diff bodies

    def _body(self, obj: ObjectDiff) -> ComposeResult:
        if self.mode == "inline":
            yield from self._inline(obj)
        elif self.mode == "tree":
            yield from self._tree(obj)
        else:
            yield from self._side(obj)

    def _inline(self, obj: ObjectDiff) -> ComposeResult:
        with Panel("Inline diff", subtitle="--no-color=false"):
            for line in obj.inline:
                yield self._inline_widget(line)

    @staticmethod
    def _inline_widget(line: DiffLine) -> Static:
        cls = {"+": "diff-line diff-add", "-": "diff-line diff-del"}.get(line.sig, "diff-line")
        colour = {"+": "$success", "-": "$error"}.get(line.sig, "$text-muted")
        return Static(_diff_line(str(line.ln), line.sig, line.text, sig_colour=colour), classes=cls)

    def _side(self, obj: ObjectDiff) -> ComposeResult:
        src, tgt = self._sides(obj)
        with Horizontal(classes="sides"):
            with VerticalScroll(classes="side left"):
                yield Static("● SOURCE · acme_prod", classes="side-head src")
                for ln, sig, text, cls in src:
                    yield Static(_diff_line(ln, sig, text), classes=cls)
            with VerticalScroll(classes="side"):
                yield Static("● TARGET · acme_staging", classes="side-head tgt")
                for ln, sig, text, cls in tgt:
                    yield Static(_diff_line(ln, sig, text), classes=cls)

    @staticmethod
    def _sides(
        obj: ObjectDiff,
    ) -> tuple[list[tuple[str, str, str, str]], list[tuple[str, str, str, str]]]:
        """Return (source_lines, target_lines) as (ln, sig, text, css) tuples."""
        if obj.source and obj.target:
            esrc = [(str(i + 1), " ", t, "diff-line") for i, t in enumerate(obj.source)]
            etgt = [(str(i + 1), " ", t, "diff-line") for i, t in enumerate(obj.target)]
            return esrc, etgt
        src: list[tuple[str, str, str, str]] = []
        tgt: list[tuple[str, str, str, str]] = []
        snum = tnum = 1
        for line in obj.inline:
            if line.sig == "+":
                tgt.append((str(tnum), "+", line.text, "diff-line diff-add"))
                src.append(("", "", "", "diff-line"))
                tnum += 1
            elif line.sig == "-":
                src.append((str(snum), "-", line.text, "diff-line diff-del"))
                tgt.append(("", "", "", "diff-line"))
                snum += 1
            else:
                src.append((str(snum), " ", line.text, "diff-line"))
                tgt.append((str(tnum), " ", line.text, "diff-line"))
                snum += 1
                tnum += 1
        return src, tgt

    def _tree(self, obj: ObjectDiff) -> ComposeResult:
        with Panel("Tree diff", subtitle="column-level breakdown"):
            yield Static(f"[$primary]◈ {obj.title}[/]", classes="diff-line")
            yield Static("  [$text-muted]▾ statements[/]", classes="diff-line")
            for line in obj.inline:
                glyph, colour, cls = {
                    "+": ("+", "$success", "diff-line diff-add"),
                    "-": ("-", "$error", "diff-line diff-del"),
                }.get(line.sig, ("·", "$text-muted", "diff-line"))
                yield Static(f"    [{colour}]{glyph}[/] {sql_markup(line.text)}", classes=cls)

    # ----------------------------------------------------------------- events

    def on_click(self, event: events.Click) -> None:
        wid = getattr(event.widget, "id", None) or ""
        if wid.startswith("mode-"):
            self.mode = wid.removeprefix("mode-")
        elif wid.startswith("jump-"):
            keys = list(DIFFS)
            self.object_key = keys[int(wid.removeprefix("jump-"))]
        elif wid == "act-ai":
            self.post_message(AiRequested(self.object_key))
        elif wid == "act-accept":
            self.notify(f"accepted {self.object_key}", severity="information")
        elif wid == "act-skip":
            self.notify(f"skipped {self.object_key}", severity="warning")
