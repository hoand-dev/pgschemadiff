"""Show current TUI settings and a redacted selected-profile summary."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from pgschemadiff.presentation.tui.views._common import Panel, SectionHeader

if TYPE_CHECKING:
    from pathlib import Path

    from textual.app import ComposeResult

    from pgschemadiff.presentation.tui.session import TuiSession


from pgschemadiff.presentation.tui.views._common import markup


class SettingsView(Widget):
    """Render real runtime state; values in this view are read-only."""

    DEFAULT_CSS = """
    SettingsView { height: 1fr; }
    SettingsView > VerticalScroll { height: 1fr; padding: 1 2; }
    SettingsView Static { height: auto; }
    """

    def compose(self) -> ComposeResult:
        yield SectionHeader("Settings", "runtime values · profile credentials omitted")
        with VerticalScroll():
            with Panel("Appearance"):
                yield Static("", id="settings-theme")
            with Panel("Runtime"):
                yield Static("", id="settings-diff-mode")
            with Panel("Apply defaults"):
                yield Static("Lock timeout default: 5000 ms")
                yield Static("Statement timeout default: 0 ms (unlimited)")
            with Panel("Profile"):
                yield Static("", id="settings-profile-path")
                yield Static("", id="settings-profile-summary")

    def update_from_session(
        self,
        session: TuiSession,
        *,
        theme: str,
        diff_mode: str,
        profile_path: Path | None,
    ) -> None:
        """Refresh display values without serializing profile credentials."""
        self.query_one("#settings-theme", Static).update(
            markup("Theme: $theme · gT toggles", theme=theme)
        )
        self.query_one("#settings-diff-mode", Static).update(
            markup("Diff mode (runtime): $mode", mode=diff_mode)
        )
        self.query_one("#settings-profile-path", Static).update(
            markup("Profile path: $path", path=profile_path or "not configured")
        )

        profile = session.selected_profile
        if profile is None:
            self.query_one("#settings-profile-summary", Static).update("No profile selected.")
            return

        schemas = ", ".join(profile.schemas) if profile.schemas else "all"
        ignore_state = (
            f"unsupported ({len(profile.ignore_patterns)} configured)"
            if profile.ignore_patterns
            else "none (0)"
        )
        summary = markup(
            "Name: $name\n"
            "Source: $source_host:$source_port · database $source_database · user $source_user\n"
            "Target: $target_host:$target_port · database $target_database · user $target_user\n"
            "Schemas: $schemas\n"
            "Mode: $mode\n"
            "Ignore patterns: $ignore_state",
            name=profile.name,
            source_host=profile.source.host,
            source_port=profile.source.port,
            source_database=profile.source.database,
            source_user=profile.source.user,
            target_host=profile.target.host,
            target_port=profile.target.port,
            target_database=profile.target.database,
            target_user=profile.target.user,
            schemas=schemas,
            mode=profile.mode,
            ignore_state=ignore_state,
        )
        self.query_one("#settings-profile-summary", Static).update(summary)
