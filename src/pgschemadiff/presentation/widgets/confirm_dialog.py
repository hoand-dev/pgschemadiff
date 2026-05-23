"""Modal dialog xác nhận hành động nguy hiểm."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConfirmDialog(ModalScreen[bool]):
    """Hiện modal hỏi xác nhận. Callback nhận True (confirm) hoặc False (cancel)."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
    }
    ConfirmDialog > Vertical {
        background: #313244;
        border: solid #45475a;
        padding: 1 2;
        width: 56;
        height: auto;
    }
    ConfirmDialog #dialog-title {
        text-style: bold;
        color: #f38ba8;
        margin-bottom: 1;
    }
    ConfirmDialog #dialog-body {
        color: #cdd6f4;
        margin-bottom: 2;
    }
    ConfirmDialog #dialog-buttons {
        height: 3;
    }
    ConfirmDialog #dialog-buttons Button {
        margin-right: 1;
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
                yield Button("Delete", id="btn-confirm", classes="-danger")
                yield Button("Cancel", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)
