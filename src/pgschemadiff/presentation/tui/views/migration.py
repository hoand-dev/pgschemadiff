"""Migration view (``gm``) — generated SQL, exec plan, lock estimates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.markup import escape
from textual.containers import Horizontal, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from pgschemadiff.presentation.tui._mock import (
    LOCK_ESTIMATES,
    MIGRATION_LINES,
    MIGRATION_STATS,
    MIGRATION_TOGGLES,
    ROLLBACK_LINES,
    MigLine,
)
from pgschemadiff.presentation.tui.views._common import (
    AiRequested,
    ApplyRequested,
    Panel,
    SectionHeader,
    sql_markup,
)

if TYPE_CHECKING:
    from textual import events
    from textual.app import ComposeResult

# class -> (sig glyph, sig colour, line css)
_LINE_STYLE = {
    "add": ("+", "$success", "diff-add"),
    "del": ("-", "$error", "diff-del"),
    "mod": ("~", "$warning", "diff-mod"),
    "warn": ("!", "$warning", ""),
    "err": ("!", "$error", ""),
    "conflict": ("!", "$error", "conflict"),
    "kw": (" ", "$text-muted", ""),
    "com": (" ", "$text-muted", ""),
    "": (" ", "$text-muted", ""),
}


def _mig_widget(line: MigLine) -> Static:
    glyph, colour, cls = _LINE_STYLE.get(line.cls, _LINE_STYLE[""])
    num = f"[$text-muted dim]{line.ln:>3}[/]"
    body = sql_markup(line.text) if line.text else ""
    css = f"diff-line {cls}".strip()
    return Static(f"{num} [{colour}]{glyph}[/] {body}", classes=css)


class MigrationView(Widget):
    """The topo-sorted migration script plus its execution plan."""

    show_rollback: reactive[bool] = reactive(False, recompose=True)

    DEFAULT_CSS = """
    MigrationView { height: 1fr; }
    MigrationView > VerticalScroll { height: 1fr; padding: 1 2; }
    MigrationView .toolbar { height: 1; margin-bottom: 1; }
    MigrationView .action { padding: 0 1; margin-left: 1; background: $boost; color: $text; }
    MigrationView .action.primary { background: $primary; color: $background; text-style: bold; }
    MigrationView .action:hover { background: $surface-lighten-1; }
    MigrationView .cols { height: auto; }
    MigrationView .script-col { width: 2fr; margin-right: 1; }
    MigrationView .side-col { width: 1fr; }
    MigrationView .tabs { height: 1; }
    MigrationView .tab {
        width: 12;
        content-align: center middle;
        background: $boost;
        color: $text-muted;
        margin-right: 1;
    }
    MigrationView .tab.active { background: $primary; color: $background; text-style: bold; }
    MigrationView .script { height: 24; background: $panel; }
    MigrationView .diff-line { padding: 0 1; height: 1; }
    MigrationView .diff-add { background: $success 10%; }
    MigrationView .diff-del { background: $error 10%; }
    MigrationView .diff-mod { background: $warning 10%; }
    MigrationView .conflict { color: $text-muted; text-style: italic; }
    MigrationView .footer { color: $text-muted; padding: 0 1; }
    """

    def compose(self) -> ComposeResult:
        crumb = "generated · 97 lines · 25 changes · 1 conflict skipped"
        yield SectionHeader("Migration script", crumb)
        with VerticalScroll():
            with Horizontal(classes="toolbar"):
                yield Static("save .sql", classes="action", id="mig-save")
                yield Static("⌘a AI review", classes="action", id="mig-ai")
                yield Static("dry-run", classes="action", id="mig-dry")
                yield Static("ga apply →", classes="action primary", id="mig-apply")
            with Horizontal(classes="cols"):
                yield from self._script_panel()
                with VerticalScroll(classes="side-col"):
                    yield from self._side_panels()

    def _script_panel(self) -> ComposeResult:
        name = "rollback.sql" if self.show_rollback else "migration_20260523_142208.sql"
        with Panel(name, classes="script-col"):
            with Horizontal(classes="tabs"):
                fcls = "tab" if self.show_rollback else "tab active"
                rcls = "tab active" if self.show_rollback else "tab"
                yield Static("forward", classes=fcls, id="mig-fwd")
                yield Static("rollback", classes=rcls, id="mig-rbk")
            with VerticalScroll(classes="script"):
                if self.show_rollback:
                    for i, text in enumerate(ROLLBACK_LINES, start=1):
                        yield Static(
                            f"[$text-muted dim]{i:>3}[/]   {sql_markup(text)}",
                            classes="diff-line",
                        )
                else:
                    for line in MIGRATION_LINES:
                        yield _mig_widget(line)
            yield Static(
                "[$text-muted]line 1/97 · col 1 · sql · utf-8 · unix · 4 spaces[/]"
                "   [$text-muted dim]sha256:b71f…ce4a[/]",
                classes="footer",
            )

    def _side_panels(self) -> ComposeResult:
        with Panel("Execution plan"):
            for label, on, hint in MIGRATION_TOGGLES:
                sw = "[$success]●[/]" if on else "[$text-muted]○[/]"
                yield Static(f"{sw} [$text]{label}[/]  [$text-muted dim]{escape(hint)}[/]")
            yield Static(
                "\n[$warning]⚠[/] public.users — ALTER COLUMN TYPE locks table (~14m est)."
            )
            yield Static("[$error]✗[/] public.legacy_invites — DROP destroys 4,217 rows.")
        with Panel("Lock estimate", subtitle="pg_locks · row counts"):
            yield Static(f"[$text-muted bold]{'step':<22}{'lock':<16}{'rows':<8}est[/]")
            for le in LOCK_ESTIMATES:
                colour = {"warn": "$warning", "err": "$error", "ok": "$success"}.get(
                    le.sev, "$text"
                )
                yield Static(f"[{colour}]{escape(le.step):<22}{le.lock:<16}{le.rows:<8}{le.est}[/]")
        with Panel("Stats"):
            for label, value, sev in MIGRATION_STATS:
                colour = {"warn": "$warning", "err": "$error"}.get(sev, "$text")
                yield Static(f"[$text-muted]{label:<16}[/] [{colour} bold]{value}[/]")

    # ----------------------------------------------------------------- events

    def on_click(self, event: events.Click) -> None:
        wid = getattr(event.widget, "id", None) or ""
        if wid == "mig-fwd":
            self.show_rollback = False
        elif wid == "mig-rbk":
            self.show_rollback = True
        elif wid == "mig-apply":
            self.post_message(ApplyRequested())
        elif wid == "mig-ai":
            self.post_message(AiRequested())
        elif wid == "mig-dry":
            self.notify("dry-run queued — see Apply view", severity="information")
        elif wid == "mig-save":
            self.notify("saved migration_20260523_142208.sql", severity="information")
