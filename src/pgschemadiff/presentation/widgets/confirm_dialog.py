"""Modal confirm / cancel dialog."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmDialog(ModalScreen[bool | None]):
    """Confirm / Cancel modal. Dismisses True on confirm, None on cancel."""

    BINDINGS = [Binding("escape", "cancel", show=False)]

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
    }
    #confirm-dialog {
        background: #313244;
        border: thick #89b4fa;
        padding: 1 2;
        width: 60;
        height: auto;
    }
    #confirm-title {
        text-style: bold;
        color: #cdd6f4;
        margin-bottom: 1;
    }
    #confirm-body {
        color: #bac2de;
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

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(self._title, id="confirm-title")
            yield Static(self._body, id="confirm-body")
            with Horizontal(id="confirm-buttons"):
                yield Button("Cancel", id="btn-cancel")
                yield Button("Delete", id="btn-delete", classes="-danger")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-delete":
            self.dismiss(True)
        else:
            self.dismiss(None)
