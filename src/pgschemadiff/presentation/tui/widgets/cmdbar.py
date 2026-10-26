"""Vim ``:`` command bar.

In *hint* mode it shows supported palette commands; in *command* mode it becomes
an :class:`Input` whose ``submitted`` event the app dispatches to the
command parser.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Label, Static

from pgschemadiff.presentation.tui.views._common import markup

if TYPE_CHECKING:
    from textual.app import ComposeResult


class Cmdbar(Widget):
    """Bottom command bar — command hints or vim ``:`` input."""

    DEFAULT_CSS = """
    Cmdbar { height: 5; background: $panel; color: $text; }
    Cmdbar > Vertical { height: 5; }
    Cmdbar Horizontal { height: 1; }
    Cmdbar #hint-row Static { height: 1; padding: 0 1; color: $text-muted; }
    Cmdbar #hint-row #hint-msg { dock: right; color: $text-muted; }
    Cmdbar #input-row { display: none; height: 1; }
    Cmdbar #input-row .prompt { color: $primary; text-style: bold; padding: 0 1; }
    Cmdbar #input-row Input {
        background: $panel;
        color: $text;
        border: none;
        padding: 0;
    }
    Cmdbar.command-mode { height: 1; }
    Cmdbar.command-mode > Vertical { height: 1; }
    Cmdbar.command-mode #hint-row { display: none; }
    Cmdbar.command-mode #input-row { display: block; }
    """

    mode: reactive[str] = reactive("normal")
    hint: reactive[str] = reactive("press ? for help")

    HINTS = (
        ":o/:overview",
        ":d/:diff [qualified-name]",
        ":m/:migration",
        ":a/:apply [--dry-run]",
        ":h/:history",
        ":c/:conn/:connection",
        ":conn switch <profile>",
        ":rollback <id>",
        ":set bg=mocha|latte",
        ":s/:settings",
        ":help/?",
        ":q/:quit",
    )

    def compose(self) -> ComposeResult:
        with Vertical(id="hint-row"):
            for start in range(0, len(self.HINTS), 3):
                command_row = "  ".join(self.HINTS[start : start + 3])
                yield Static(markup("$commands", commands=command_row), classes="commands")
            yield Label(self.hint, id="hint-msg")
        with Horizontal(id="input-row"):
            yield Label(":", classes="prompt")
            yield Input(
                placeholder="type a supported command",
                id="cmd-input",
            )

    def watch_mode(self, mode: str) -> None:
        self.set_class(mode == "command", "command-mode")
        if mode == "command":
            with contextlib.suppress(Exception):
                self.query_one("#cmd-input", Input).focus()

    def watch_hint(self, hint: str) -> None:
        try:
            self.query_one("#hint-msg", Label).update(hint)
        except Exception:
            return
