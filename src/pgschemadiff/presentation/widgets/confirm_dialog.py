"""Modal confirmation dialog."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmDialog(ModalScreen[bool]):
    """Two-button Yes/No modal that returns True on confirm, False on cancel."""

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
    }
    ConfirmDialog > Vertical {
        background: #313244;
        border: solid #45475a;
        padding: 1 2;
        width: 50;
        height: auto;
    }
    ConfirmDialog #dialog-title {
        text-style: bold;
        color: #cdd6f4;
        margin-bottom: 1;
    }
    ConfirmDialog #dialog-body {
        color: #bac2de;
        margin-bottom: 2;
    }
    ConfirmDialog Horizontal {
        height: 3;
        align-horizontal: right;
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
            yield Static(self._title, id="dialog-title")
            yield Static(self._body, id="dialog-body")
            with Horizontal():
                yield Button("Cancel", id="btn-cancel")
                yield Button("Delete", id="btn-confirm", classes="-danger")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-confirm")
