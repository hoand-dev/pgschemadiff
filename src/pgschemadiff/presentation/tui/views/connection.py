"""Connection view (``gc``) — real profile fields and comparison action."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, DataTable, Static

from pgschemadiff.presentation.tui.views._common import Panel, SectionHeader, markup

if TYPE_CHECKING:
    from pathlib import Path

    from textual.app import ComposeResult
    from textual.content import Content

    from pgschemadiff.domain.models import ConnectionInfo, Profile
    from pgschemadiff.presentation.tui.session import TuiSession


class TestBothRequested(Message):
    """Request a real comparison through the app's read worker."""


class ProfileSelected(Message):
    """Select profile at the given session index without carrying secrets."""

    def __init__(self, index: int) -> None:
        super().__init__()
        self.index = index


def _connection_markup(
    profile: Profile,
    connection: ConnectionInfo,
    *,
    role: str,
    schemas: str,
    table_count: int | None,
) -> Content:
    header_template = (
        "[$secondary bold]● $role[/]  [$primary]$profile[/]"
        if role == "source"
        else "[$warning bold]● $role[/]  [$primary]$profile[/]"
    )
    head = markup(header_template, role=role.upper(), profile=profile.name)
    body = markup(
        "[$text-muted]host           [/] [$text]$host[/]\n"
        "[$text-muted]port           [/] [$text]$port[/]\n"
        "[$text-muted]database       [/] [$text]$database[/]\n"
        "[$text-muted]user           [/] [$text]$user[/]\n"
        "[$text-muted]schemas        [/] [$text]$schemas[/]\n"
        "[$text-muted]SSL            [/] [$text]n/a[/]\n"
        "[$text-muted]server version [/] [$text]n/a[/]\n"
        "[$text-muted]latency        [/] [$text]n/a[/]\n"
        "[$text-muted]tables         [/] [$text]$tables[/]\n"
        "[$text-muted]size           [/] [$text]n/a[/]",
        host=connection.host,
        port=connection.port,
        database=connection.database,
        user=connection.user,
        schemas=schemas,
        tables="n/a" if table_count is None else table_count,
    )
    return head.append("\n\n").append(body)


class ConnectionView(Widget):
    """Render loaded profiles without exposing DSNs or passwords."""

    DEFAULT_CSS = """
    ConnectionView { height: 1fr; }
    ConnectionView > VerticalScroll { height: 1fr; padding: 1 2; }
    ConnectionView .toolbar { height: auto; padding: 0 2 1 2; }
    ConnectionView .cards { height: auto; }
    ConnectionView .cards Panel { width: 1fr; margin: 0 1 1 0; }
    ConnectionView .arrow { width: 5; content-align: center middle; color: $text-muted; }
    ConnectionView #connection-status { height: auto; padding: 0 2; color: $warning; }
    ConnectionView #connection-empty { height: auto; color: $text-muted; }
    ConnectionView #saved-profiles { height: auto; max-height: 10; }
    """

    def compose(self) -> ComposeResult:
        yield SectionHeader("Connections", "pgschemadiff · connection")
        with Horizontal(classes="toolbar"):
            yield Button("^t  Test both", id="btn-test-both", variant="primary", disabled=True)
        yield Static(" ", id="connection-status")
        with VerticalScroll():
            with Horizontal(classes="cards"):
                with Panel("● SOURCE"):
                    yield Static("No profile selected.", id="connection-source")
                yield Static("→", classes="arrow")
                with Panel("● TARGET"):
                    yield Static("No profile selected.", id="connection-target")
            with Panel("Compare options", subtitle="read-only"):
                yield Static("No profile selected.", id="connection-options")
            with Panel("Saved profiles"):
                yield Static("", id="connection-profile-path")
                yield DataTable(id="saved-profiles", cursor_type="row")
                yield Static("", id="connection-empty")

    def on_mount(self) -> None:
        self.query_one("#saved-profiles", DataTable).add_columns("Name", "Route", "Status")

    def update_session(
        self,
        session: TuiSession,
        *,
        profiles_path: Path | None,
        status: str | None = None,
    ) -> None:
        """Render current session state using only explicit non-secret fields."""
        path_text = (
            markup("Profiles read from $path", path=profiles_path)
            if profiles_path is not None
            else "Profile path unavailable"
        )
        self.query_one("#connection-profile-path", Static).update(path_text)
        self.query_one("#connection-status", Static).update(
            markup("$status", status=status) if status else " "
        )

        table = self.query_one("#saved-profiles", DataTable)
        table.clear()
        for index, profile in enumerate(session.profiles):
            route = f"{profile.source.database} → {profile.target.database}"
            current = profile == session.selected_profile
            table.add_row(profile.name, route, "✓ current" if current else "switch", key=str(index))

        selected = session.selected_profile
        empty = self.query_one("#connection-empty", Static)
        empty.display = selected is None
        if selected is None:
            if status == "Could not load profiles.":
                empty.update("Profiles unavailable.")
            elif not session.profiles and profiles_path is not None:
                empty.update(
                    markup("No profiles found. Profiles are read from $path.", path=profiles_path)
                )
            else:
                empty.update("No profile selected.")
            self.query_one("#connection-source", Static).update("No profile selected.")
            self.query_one("#connection-target", Static).update("No profile selected.")
            self.query_one("#connection-options", Static).update("No profile selected.")
            self.query_one("#btn-test-both", Button).disabled = True
            return

        schemas = ", ".join(selected.schemas) if selected.schemas else "all schemas"
        source_count: int | None = None
        target_count: int | None = None
        if session.last_comparison is not None:
            source_count = len(session.last_comparison.source.all_tables())
            target_count = len(session.last_comparison.target.all_tables())
        self.query_one("#connection-source", Static).update(
            _connection_markup(
                selected,
                selected.source,
                role="source",
                schemas=schemas,
                table_count=source_count,
            )
        )
        self.query_one("#connection-target", Static).update(
            _connection_markup(
                selected,
                selected.target,
                role="target",
                schemas=schemas,
                table_count=target_count,
            )
        )
        filters = "unsupported profile filters" if selected.ignore_patterns else "none"
        self.query_one("#connection-options", Static).update(
            markup(
                "[$text-muted]Include schemas[/]  [$text]$schemas[/]\n"
                "[$text-muted]Exclude tables[/]   [$text]$filters[/]\n"
                "[$text-muted]Mode[/]             [$text]$mode[/]",
                schemas=schemas,
                filters=filters,
                mode=selected.mode,
            )
        )
        self.query_one("#btn-test-both", Button).disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-test-both":
            self.post_message(TestBothRequested())
            event.stop()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.post_message(ProfileSelected(event.cursor_row))
        event.stop()
