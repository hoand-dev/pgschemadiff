"""Modal confirmation dialog."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConfirmDialog(ModalScreen[bool]):
    """A modal that asks the user to confirm or cancel an action."""

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
    }
    ConfirmDialog > Vertical {
        background: #313244;
        border: thick #89b4fa;
        padding: 1 2;
        width: 60;
        height: auto;
    }
    ConfirmDialog #dialog-title {
        text-style: bold;
        color: #cdd6f4;
        margin-bottom: 1;
    }
    ConfirmDialog #dialog-body {
        color: #a6adc8;
        margin-bottom: 2;
    }
    ConfirmDialog #dialog-buttons {
        height: 3;
        align: right middle;
    }
    ConfirmDialog #dialog-buttons Button {
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
            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="btn-cancel")
                yield Button("Delete", id="btn-confirm", classes="-danger")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-confirm")
