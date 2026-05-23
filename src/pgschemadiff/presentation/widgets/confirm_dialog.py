"""Modal confirmation dialog."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConfirmDialog(ModalScreen[bool]):
    """A modal dialog asking the user to confirm or cancel an action."""

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
    }
    ConfirmDialog > Vertical {
        background: $surface;
        border: thick $primary;
        padding: 1 2;
        width: 60;
        height: auto;
    }
    ConfirmDialog #dialog-title {
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }
    ConfirmDialog #dialog-body {
        margin-bottom: 1;
    }
    ConfirmDialog Horizontal {
        align: right middle;
        height: auto;
        margin-top: 1;
    }
    ConfirmDialog Button {
        margin-left: 1;
    }
    """

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._title, id="dialog-title")
            yield Label(self._body, id="dialog-body")
            with Horizontal():
                yield Button("Cancel", id="btn-cancel", variant="default")
                yield Button("Delete", id="btn-confirm", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-confirm")
