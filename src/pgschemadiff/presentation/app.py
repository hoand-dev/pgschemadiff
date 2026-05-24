"""Top-level Textual App."""

from __future__ import annotations

from pathlib import Path

from textual.app import App

from pgschemadiff.infrastructure.config.yaml_loader import ProfileLoader
from pgschemadiff.presentation.screens.home import HomeScreen


class PgSchemaDiffApp(App):
    """Main TUI application."""

    CSS_PATH = Path(__file__).parent / "styles.tcss"
    TITLE = "pgschemadiff"

    def __init__(self, config_path: Path) -> None:
        super().__init__()
        self.config_path = config_path

    def on_mount(self) -> None:
        loader = ProfileLoader(self.config_path)
        profiles = loader.load()
        self.push_screen(HomeScreen(profiles))
