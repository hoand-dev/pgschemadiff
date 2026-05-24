"""Modal confirm dialog."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConfirmDialog(ModalScreen[bool]):
    """Asks the user to confirm or cancel a destructive action.

    Dismissed with True on confirm, False on cancel/escape.
    """

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
    }
    #confirm-dialog {
        background: #313244;
        border: solid #45475a;
        padding: 1 2;
        width: 60;
        height: auto;
    }
    #confirm-title {
        text-style: bold;
        color: #f38ba8;
        margin-bottom: 1;
    }
    #confirm-body {
        color: #cdd6f4;
        margin-bottom: 2;
    }
    #confirm-buttons {
        height: 3;
        align-horizontal: right;
    }
    #confirm-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._dialog_title = title
        self._dialog_body = body

    def compose(self) -> ComposeResult:
        with Container(id="confirm-dialog"):
            yield Label(self._dialog_title, id="confirm-title")
            yield Label(self._dialog_body, id="confirm-body")
            with Horizontal(id="confirm-buttons"):
                yield Button("Cancel", id="btn-cancel")
                yield Button("Delete", id="btn-confirm", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)
