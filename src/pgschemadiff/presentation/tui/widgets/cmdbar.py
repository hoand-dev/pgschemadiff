"""Vim ``:`` command bar.

In *hint* mode it shows the chord cheatsheet; in *command* mode it becomes
an :class:`Input` whose ``submitted`` event the app dispatches to the
command parser.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Label

if TYPE_CHECKING:
    from textual.app import ComposeResult


class Cmdbar(Widget):
    """Bottom command bar — hint row or vim ``:`` input."""

    DEFAULT_CSS = """
    Cmdbar { height: 1; background: $panel; color: $text; }
    Cmdbar Horizontal { height: 1; }
    Cmdbar #hint-row Label { padding: 0 1; color: $text-muted; }
    Cmdbar #hint-row .key { color: $warning; text-style: bold; }
    Cmdbar #hint-row #hint-msg { dock: right; color: $text-muted; }
    Cmdbar #input-row { display: none; }
    Cmdbar #input-row .prompt { color: $primary; text-style: bold; padding: 0 1; }
    Cmdbar #input-row Input {
        background: $panel;
        color: $text;
        border: none;
        padding: 0;
    }
    Cmdbar.command-mode #hint-row { display: none; }
    Cmdbar.command-mode #input-row { display: block; }
    """

    mode: reactive[str] = reactive("normal")
    hint: reactive[str] = reactive("press ? for help")

    HINTS = (
        (":", "command"),
        ("?", "help"),
        ("gc", "conn"),
        ("go", "overview"),
        ("gd", "diff"),
        ("gm", "migration"),
        ("ga", "apply"),
        ("gh", "history"),
        ("gs", "settings"),
        ("gT", "theme"),
        ("ZZ", "quit"),
    )

    def compose(self) -> ComposeResult:
        with Horizontal(id="hint-row"):
            for key, label in self.HINTS:
                yield Label(f"[$warning]{key}[/] {label}", classes="key")
            yield Label(self.hint, id="hint-msg")
        with Horizontal(id="input-row"):
            yield Label(":", classes="prompt")
            yield Input(
                placeholder="diff users · apply --dry-run · set bg=latte · q",
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
