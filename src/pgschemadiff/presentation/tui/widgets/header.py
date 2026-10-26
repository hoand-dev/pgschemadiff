"""Top header strip — brand, mode badge, source→target pills."""

from __future__ import annotations

from importlib import metadata
from typing import TYPE_CHECKING

from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

from pgschemadiff.presentation.tui.views._common import markup

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.content import Content

    from pgschemadiff.domain.models import Profile


def _package_version() -> str:
    try:
        return metadata.version("pgschemadiff")
    except metadata.PackageNotFoundError:
        return "dev"


class HeaderBar(Widget):
    """The top header bar (brand, mode, connection pills)."""

    DEFAULT_CSS = """
    HeaderBar {
        height: 1;
        background: $surface;
        color: $text;
    }
    HeaderBar Horizontal { height: 1; }
    HeaderBar .brand { color: $primary; text-style: bold; padding: 0 1; }
    HeaderBar .mode { background: $success; color: $background; padding: 0 1; text-style: bold; }
    HeaderBar .mode.command { background: $warning; }
    HeaderBar .mode.insert { background: $accent 50%; }
    HeaderBar .pill { background: $boost; color: $text-muted; padding: 0 1; }
    HeaderBar .pill .src { color: $secondary; }
    HeaderBar .pill .tgt { color: $warning; }
    HeaderBar .right { padding: 0 1; color: $text-muted; }
    """

    mode: reactive[str] = reactive("normal")

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label(
                markup("◈ pgschemadiff v$version", version=_package_version()),
                id="brand",
                classes="brand",
            )
            yield Label(self.mode.upper(), id="mode-badge", classes="mode")
            yield Label("src → —  tgt → —", id="connection-pills", classes="pill")
            yield Label("  :cmd", classes="right")

    def update_profile(self, profile: Profile | None) -> None:
        """Render only selected profile name and database labels."""
        if profile is None:
            label: str | Content = "src → —  tgt → —"
        else:
            label = markup(
                "src → [b]$profile / $source[/b]  tgt → [b]$profile / $target[/b]",
                profile=profile.name,
                source=profile.source.database,
                target=profile.target.database,
            )
        self.query_one("#connection-pills", Label).update(label)

    def watch_mode(self, mode: str) -> None:
        try:
            badge = self.query_one("#mode-badge", Label)
        except Exception:
            return
        badge.update(mode.upper())
        badge.set_class(mode == "command", "command")
        badge.set_class(mode == "insert", "insert")
