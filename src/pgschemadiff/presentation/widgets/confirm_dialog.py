"""Modal confirm dialog dùng chung trong toàn app."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmDialog(ModalScreen[bool]):
    """Hiện modal hỏi xác nhận, dismiss với True (confirm) hoặc False (cancel)."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
    }

    ConfirmDialog > Vertical {
        background: #313244;
        border: solid #45475a;
        padding: 1 2;
        width: 60;
        height: auto;
    }

    ConfirmDialog #dialog-title {
        color: #f38ba8;
        text-style: bold;
        margin-bottom: 1;
    }

    ConfirmDialog #dialog-body {
        color: #cdd6f4;
        margin-bottom: 2;
    }

    ConfirmDialog #dialog-actions {
        height: 3;
        align-horizontal: right;
    }

    ConfirmDialog #dialog-actions Button {
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
            with Horizontal(id="dialog-actions"):
                yield Button("Cancel", id="btn-cancel")
                yield Button("Delete", id="btn-confirm", classes="-danger")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)
