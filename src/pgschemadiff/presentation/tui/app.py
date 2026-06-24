"""The Textual application class — ``PgsdApp``.

Implements the vim-style chord dispatcher, theme cycling, command palette,
and screen composition described in ``docs/ui-design.md``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import App
from textual.binding import Binding
from textual.widgets import ContentSwitcher, Input

from pgschemadiff.presentation.tui._mock import ai_for
from pgschemadiff.presentation.tui.screens import AiModal, HelpScreen, MainScreen
from pgschemadiff.presentation.tui.views import DiffView
from pgschemadiff.presentation.tui.views._common import (
    AiRequested,
    ApplyRequested,
    DiffRequested,
)
from pgschemadiff.presentation.tui.widgets import (
    Cmdbar,
    HeaderBar,
    Statusbar,
    TabActivated,
    ViewTabs,
)
from pgschemadiff.shared.logging import get_logger

if TYPE_CHECKING:
    from textual.events import Key

_VIEW_CHORDS: dict[str, str] = {
    "c": "connection",
    "o": "overview",
    "d": "diff",
    "m": "migration",
    "a": "apply",
    "h": "history",
    "s": "settings",
}

_THEMES: tuple[str, str] = ("catppuccin-mocha", "catppuccin-latte")


class PgsdApp(App[None]):
    """The pgschemadiff Textual TUI."""

    TITLE = "pgschemadiff"
    SUB_TITLE = "schema diff & migration"

    # Start in vim "normal" mode: nothing grabs the keyboard, so chord keys
    # (g…, Z…, space…) reach ``on_key``.  Focus is taken explicitly — ``:`` for
    # the command bar, ``/`` for the sidebar search.
    AUTO_FOCUS = None

    BINDINGS = [  # noqa: RUF012 — base class types this as a mutable list
        Binding("escape", "leave_mode", "leave mode"),
        Binding("question_mark", "open_help", "help"),
        Binding("colon", "enter_command", "command"),
        Binding("ctrl+b", "toggle_sidebar", "toggle sidebar"),
    ]

    CSS = """
    Screen { background: $background; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._mode = "normal"
        self._chord: str | None = None
        self._active_view = "overview"
        self._pgsd_logger = get_logger("pgsd.tui")

    # ------------------------------------------------------------------ life-cycle

    def get_default_screen(self) -> MainScreen:
        # Make MainScreen the base of the screen stack so ``app.query_one(...)``
        # reaches its children without going through a pushed-on-top layer.
        return MainScreen()

    def on_mount(self) -> None:
        self.theme = _THEMES[0]

    # ------------------------------------------------------------------ helpers

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        try:
            self.query_one(HeaderBar).mode = mode
            self.query_one(Statusbar).mode = mode
            self.query_one(Cmdbar).mode = mode
        except Exception:
            return

    def _set_hint(self, hint: str) -> None:
        try:
            self.query_one(Cmdbar).hint = hint
        except Exception:
            return

    def switch_view(self, view_id: str) -> None:
        """Switch the main content area + tab indicator + statusbar."""
        switcher = self.query_one("#content", ContentSwitcher)
        switcher.current = view_id
        self.query_one(ViewTabs).active = view_id
        self.query_one(Statusbar).view = view_id
        self._active_view = view_id

    def toggle_theme(self) -> None:
        current = self.theme
        next_theme = _THEMES[1] if current == _THEMES[0] else _THEMES[0]
        self.theme = next_theme
        self._set_hint(f"theme → {next_theme}")

    # ------------------------------------------------------------------ actions (Textual Binding)

    def action_leave_mode(self) -> None:
        self._chord = None
        if self._mode != "normal":
            self._set_mode("normal")
        if isinstance(self.focused, Input):
            self.set_focus(None)
        self._set_hint("press ? for help")

    def action_open_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_enter_command(self) -> None:
        self._set_mode("command")
        self._set_hint("")

    def action_toggle_sidebar(self) -> None:
        try:
            sidebar = self.query_one("#sidebar")
        except Exception:
            return
        sidebar.toggle_class("hidden")

    # ------------------------------------------------------------------ vim chord dispatch

    def on_key(self, event: Key) -> None:
        if self._mode == "command":
            return  # Input widget owns the keystrokes
        if isinstance(self.focused, Input):
            return  # the sidebar search owns the keystrokes
        if event.key == "slash":
            self._focus_search()
            event.stop()
            return
        if self._chord == "space":
            self._chord = None
            self._resolve_space_chord(event.character or event.key)
            event.stop()
            return
        if event.key == "space" and self._chord is None:
            self._chord = "space"
            self._set_hint("␣…")
            event.stop()
            return
        if event.key == "g" and self._chord is None:
            self._chord = "g"
            self._set_hint("g…")
            event.stop()
            return
        if event.key == "Z" and self._chord is None:
            self._chord = "Z"
            self._set_hint("Z…")
            event.stop()
            return
        if self._chord == "g":
            self._chord = None
            key = event.character or event.key
            if key in _VIEW_CHORDS:
                self.switch_view(_VIEW_CHORDS[key])
                self._set_hint(f"g{key} — {_VIEW_CHORDS[key]}")
                event.stop()
                return
            if key in {"T", "shift+t"}:
                self.toggle_theme()
                event.stop()
                return
            if key == "g":
                self._set_hint("top")
                event.stop()
                return
            self._set_hint("(chord cancelled)")
            return
        if self._chord == "Z":
            self._chord = None
            if (event.character or event.key) == "Z":
                self._set_hint("ZZ — bye")
                self.exit()
                event.stop()
                return
            self._set_hint("(chord cancelled)")

    # -------------------------------------------------------- tabs & command submission

    def on_tab_activated(self, message: TabActivated) -> None:
        self.switch_view(message.view_id)

    def on_input_submitted(self, message: Input.Submitted) -> None:
        cmd = (message.value or "").strip()
        message.input.value = ""
        self._set_mode("normal")
        if not cmd:
            return
        self._dispatch_command(cmd)

    # ------------------------------------------------------------------ command parser

    def _dispatch_command(self, cmd: str) -> None:
        c = cmd.lower()
        self._pgsd_logger.info("tui_command", command=c)
        if c in {"q", "quit", "zz"}:
            self.exit()
            return
        if c in {"?", "help"}:
            self.push_screen(HelpScreen())
            return
        if c.startswith(("set bg=", "set theme=")):
            theme = c.split("=", 1)[1].strip()
            mapping = {"mocha": "catppuccin-mocha", "latte": "catppuccin-latte"}
            if theme in mapping:
                self.theme = mapping[theme]
                self._set_hint(f"theme → {self.theme}")
            else:
                self._set_hint(f"E474: unknown theme: {theme}")
            return
        view_aliases = {
            "o": "overview",
            "overview": "overview",
            "d": "diff",
            "diff": "diff",
            "m": "migration",
            "migration": "migration",
            "a": "apply",
            "apply": "apply",
            "h": "history",
            "history": "history",
            "s": "settings",
            "settings": "settings",
            "config": "settings",
            "c": "connection",
            "conn": "connection",
            "connection": "connection",
        }
        first = c.split()[0]
        if first in view_aliases:
            self.switch_view(view_aliases[first])
            self._set_hint(f":{c} — executed")
            return
        if c.startswith("apply"):
            self.switch_view("apply")
            self._set_hint(":apply — executed")
            return
        if c.startswith("rollback"):
            self.switch_view("history")
            self._set_hint("rollback queued — see history")
            return
        self._set_hint(f"E492: not an editor command: {cmd}")

    # ------------------------------------------------------------------ space chord + search

    def _focus_search(self) -> None:
        try:
            self.query_one("#sidebar-search", Input).focus()
        except Exception:
            return

    def _resolve_space_chord(self, key: str) -> None:
        if self._active_view != "diff":
            self._set_hint("(space leader — open Diff first)")
            return
        diff = self.query_one("#diff", DiffView)
        if key == "i":
            self.push_screen(AiModal(ai_for(diff.object_key)))
        elif key == "a":
            self._set_hint(f"␣a — accepted {diff.object_key}")
        elif key == "s":
            self._set_hint(f"␣s — skipped {diff.object_key}")
        else:
            self._set_hint("(chord cancelled)")

    # ------------------------------------------------------------------ navigation messages

    def on_diff_requested(self, message: DiffRequested) -> None:
        self.query_one("#diff", DiffView).object_key = message.object_key
        self.switch_view("diff")
        self._set_hint(f"diff → {message.object_key}")
        message.stop()

    def on_ai_requested(self, message: AiRequested) -> None:
        self.push_screen(AiModal(ai_for(message.target)))
        message.stop()

    def on_apply_requested(self, message: ApplyRequested) -> None:
        self.switch_view("apply")
        self._set_hint(":apply — opened")
        message.stop()


def run() -> None:
    """Launch the TUI (used by ``pgsd tui`` and ``pgsd``)."""
    PgsdApp().run()


if __name__ == "__main__":  # pragma: no cover
    run()
