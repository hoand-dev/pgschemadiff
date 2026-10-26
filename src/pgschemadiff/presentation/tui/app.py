"""The Textual application class — ``PgsdApp``.

Implements the vim-style chord dispatcher, theme cycling, command palette,
and screen composition described in ``docs/ui-design.md``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from psycopg import Error as PsycopgError
from textual.app import App
from textual.binding import Binding
from textual.message import Message
from textual.widgets import ContentSwitcher, Input
from textual.worker import Worker

from pgschemadiff.presentation.tui._mock import ai_for
from pgschemadiff.presentation.tui.screens import AiModal, HelpScreen, MainScreen
from pgschemadiff.presentation.tui.session import TuiSession
from pgschemadiff.presentation.tui.views.connection import (
    ConnectionView,
    ProfileSelected,
    TestBothRequested,
)
from pgschemadiff.presentation.tui.views import DiffView
from pgschemadiff.presentation.tui.views._common import (
    AiRequested,
    ApplyRequested,
    DiffRequested,
)
from pgschemadiff.presentation.tui.widgets import (
    Cmdbar,
    HeaderBar,
    Statusbar,
    TabActivated,
    ViewTabs,
)
from pgschemadiff.shared.errors import DiffError, InspectionError
from pgschemadiff.shared.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from textual.events import Key

    from pgschemadiff.domain.models import Profile
    from pgschemadiff.presentation.composition import TuiDependencies

_VIEW_CHORDS: dict[str, str] = {
    "c": "connection",
    "o": "overview",
    "d": "diff",
    "m": "migration",
    "a": "apply",
    "h": "history",
    "s": "settings",
}

_THEMES: tuple[str, str] = ("catppuccin-mocha", "catppuccin-latte")
_LOGGED_COMMANDS: dict[str, str] = {
    "q": "quit",
    "quit": "quit",
    "zz": "quit",
    "?": "help",
    "help": "help",
    "set": "set",
    "o": "overview",
    "overview": "overview",
    "d": "diff",
    "diff": "diff",
    "m": "migration",
    "migration": "migration",
    "a": "apply",
    "apply": "apply",
    "h": "history",
    "history": "history",
    "s": "settings",
    "settings": "settings",
    "config": "settings",
    "c": "connection",
    "conn": "connection",
    "connection": "connection",
    "rollback": "rollback",
}


class ProfilesLoaded(Message):
    """Signal that profile state is ready for view refresh."""


class ComparisonCompleted(Message):
    """Signal that a successful comparison is stored in the session."""


class ComparisonFailed(Message):
    """Carry only a fixed, redacted comparison error message."""

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message


class PgsdApp(App[None]):
    """The pgschemadiff Textual TUI."""

    TITLE = "pgschemadiff"
    SUB_TITLE = "schema diff & migration"

    # Start in vim "normal" mode: nothing grabs the keyboard, so chord keys
    # (g…, Z…, space…) reach ``on_key``.  Focus is taken explicitly — ``:`` for
    # the command bar, ``/`` for the sidebar search.
    AUTO_FOCUS = None

    BINDINGS = [  # noqa: RUF012 — base class types this as a mutable list
        Binding("escape", "leave_mode", "leave mode"),
        Binding("question_mark", "open_help", "help"),
        Binding("colon", "enter_command", "command"),
        Binding("ctrl+b", "toggle_sidebar", "toggle sidebar"),
        Binding("ctrl+t", "test_both", "test both", show=False),
    ]

    CSS = """
    Screen { background: $background; }
    """

    def __init__(self, *, dependencies: TuiDependencies | None = None) -> None:
        super().__init__()
        self.dependencies = dependencies
        self.session = TuiSession()
        self._profile_load_error = False
        self._comparison_worker: Worker[None] | None = None
        self._mode = "normal"
        self._chord: str | None = None
        self._active_view = "overview"
        self._pgsd_logger = get_logger("pgsd.tui")

    # ------------------------------------------------------------------ life-cycle

    def get_default_screen(self) -> MainScreen:
        # Make MainScreen the base of the screen stack so ``app.query_one(...)``
        # reaches its children without going through a pushed-on-top layer.
        return MainScreen()

    def on_mount(self) -> None:
        self.theme = _THEMES[0]
        self.call_after_refresh(self._initialize_connection)

    def _initialize_connection(self) -> None:
        if self.dependencies is None:
            self._refresh_connection(status="No profile loader configured.")
            return
        self._refresh_connection(status="Loading profiles…")
        self.run_worker(
            self._load_profiles(),
            name="profile-load",
            group="profile-load",
            exclusive=True,
        )

    async def _load_profiles(self) -> None:
        dependencies = self.dependencies
        if dependencies is None:
            return
        try:
            profiles = await asyncio.to_thread(dependencies.profile_loader.load)
        except Exception:
            self.session.set_profiles([])
            self._profile_load_error = True
        else:
            self.session.set_profiles(profiles)
            self._profile_load_error = False
        self.post_message(ProfilesLoaded())

    def _profile_path(self) -> Path | None:
        if self.dependencies is None:
            return None
        return self.dependencies.profile_loader.config_path

    def _refresh_connection(self, *, status: str | None = None) -> None:
        self.query_one("#connection", ConnectionView).update_session(
            self.session,
            profiles_path=self._profile_path(),
            status=status,
        )

    def _start_test_both(self) -> None:
        profile = self.session.selected_profile
        if self.dependencies is None:
            self._refresh_connection(status="No profile loader configured.")
            return
        if profile is None:
            self._refresh_connection(status="No profile selected.")
            return
        if profile.ignore_patterns:
            self._report_comparison_error("unsupported profile filters")
            return
        if profile.mode != "schema-only":
            self._report_comparison_error("unsupported profile mode")
            return

        self._refresh_connection(status="Testing connections…")
        self._comparison_worker = self.run_worker(
            self._compare_profile(profile),
            name="compare-profile",
            group="database-read",
            exclusive=True,
        )

    async def _compare_profile(self, profile: Profile) -> None:
        dependencies = self.dependencies
        if dependencies is None:
            return
        try:
            result = await dependencies.compare(
                profile.source.dsn(),
                profile.target.dsn(),
                profile.schemas or None,
            )
        except Exception as exc:
            if self.session.selected_profile == profile:
                self.post_message(ComparisonFailed(self._comparison_error_message(exc)))
            return
        if self.session.selected_profile != profile:
            return
        self.session.last_comparison = result
        self.post_message(ComparisonCompleted())

    @staticmethod
    def _comparison_error_message(exc: Exception) -> str:
        if isinstance(exc, (PsycopgError, ConnectionError, TimeoutError)):
            return "Could not connect to one or both databases."
        if isinstance(exc, InspectionError):
            return "Could not inspect database schemas."
        if isinstance(exc, DiffError):
            return "Could not compare database schemas."
        return "Comparison failed."

    def _report_comparison_error(self, message: str) -> None:
        self._refresh_connection(status=message)
        self.notify(message, severity="error")

    def on_profiles_loaded(self, _message: ProfilesLoaded) -> None:
        status = "Could not load profiles." if self._profile_load_error else None
        self._refresh_connection(status=status)
        cast(MainScreen, self.screen_stack[0]).update_from_session(self.session)

    def on_comparison_completed(self, _message: ComparisonCompleted) -> None:
        self._refresh_connection(status="Comparison complete.")
        cast(MainScreen, self.screen_stack[0]).update_from_session(self.session)

    def on_comparison_failed(self, message: ComparisonFailed) -> None:
        self._report_comparison_error(message.message)
        cast(MainScreen, self.screen_stack[0]).update_from_session(self.session)

    def on_profile_selected(self, message: ProfileSelected) -> None:
        if not 0 <= message.index < len(self.session.profiles):
            return
        profile = self.session.profiles[message.index]
        if profile == self.session.selected_profile:
            return
        if self._comparison_worker is not None:
            self._comparison_worker.cancel()
            self._comparison_worker = None
        self.session.select_profile(profile)
        self._refresh_connection()
        cast(MainScreen, self.screen_stack[0]).update_from_session(self.session)

    def on_test_both_requested(self, _message: TestBothRequested) -> None:
        self._start_test_both()

    def action_test_both(self) -> None:
        self._start_test_both()

    # ------------------------------------------------------------------ helpers

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        try:
            self.query_one(HeaderBar).mode = mode
            self.query_one(Statusbar).mode = mode
            self.query_one(Cmdbar).mode = mode
        except Exception:
            return

    def _set_hint(self, hint: str) -> None:
        try:
            self.query_one(Cmdbar).hint = hint
        except Exception:
            return

    def switch_view(self, view_id: str) -> None:
        """Switch the main content area + tab indicator + statusbar."""
        switcher = self.query_one("#content", ContentSwitcher)
        switcher.current = view_id
        self.query_one(ViewTabs).active = view_id
        self.query_one(Statusbar).view = view_id
        self._active_view = view_id

    def toggle_theme(self) -> None:
        current = self.theme
        next_theme = _THEMES[1] if current == _THEMES[0] else _THEMES[0]
        self.theme = next_theme
        self._set_hint(f"theme → {next_theme}")

    # ------------------------------------------------------------------ actions (Textual Binding)

    def action_leave_mode(self) -> None:
        self._chord = None
        if self._mode != "normal":
            self._set_mode("normal")
        if isinstance(self.focused, Input):
            self.set_focus(None)
        self._set_hint("press ? for help")

    def action_open_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_enter_command(self) -> None:
        self._set_mode("command")
        self._set_hint("")

    def action_toggle_sidebar(self) -> None:
        try:
            sidebar = self.query_one("#sidebar")
        except Exception:
            return
        sidebar.toggle_class("hidden")

    # ------------------------------------------------------------------ vim chord dispatch

    def on_key(self, event: Key) -> None:
        if self._mode == "command":
            return  # Input widget owns the keystrokes
        if isinstance(self.focused, Input):
            return  # the sidebar search owns the keystrokes
        if event.key == "slash":
            self._focus_search()
            event.stop()
            return
        if self._chord == "space":
            self._chord = None
            self._resolve_space_chord(event.character or event.key)
            event.stop()
            return
        if event.key == "space" and self._chord is None:
            self._chord = "space"
            self._set_hint("␣…")
            event.stop()
            return
        if event.key == "g" and self._chord is None:
            self._chord = "g"
            self._set_hint("g…")
            event.stop()
            return
        if event.key == "Z" and self._chord is None:
            self._chord = "Z"
            self._set_hint("Z…")
            event.stop()
            return
        if self._chord == "g":
            self._chord = None
            key = event.character or event.key
            if key in _VIEW_CHORDS:
                self.switch_view(_VIEW_CHORDS[key])
                self._set_hint(f"g{key} — {_VIEW_CHORDS[key]}")
                event.stop()
                return
            if key in {"T", "shift+t"}:
                self.toggle_theme()
                event.stop()
                return
            if key == "g":
                self._set_hint("top")
                event.stop()
                return
            self._set_hint("(chord cancelled)")
            return
        if self._chord == "Z":
            self._chord = None
            if (event.character or event.key) == "Z":
                self._set_hint("ZZ — bye")
                self.exit()
                event.stop()
                return
            self._set_hint("(chord cancelled)")

    # -------------------------------------------------------- tabs & command submission

    def on_tab_activated(self, message: TabActivated) -> None:
        self.switch_view(message.view_id)

    def on_input_submitted(self, message: Input.Submitted) -> None:
        cmd = (message.value or "").strip()
        message.input.value = ""
        self._set_mode("normal")
        if not cmd:
            return
        self._dispatch_command(cmd)

    # ------------------------------------------------------------------ command parser

    def _dispatch_command(self, cmd: str) -> None:
        c = cmd.lower()
        first = c.split(maxsplit=1)[0]
        self._pgsd_logger.info("tui_command", command=_LOGGED_COMMANDS.get(first, "unknown"))
        if c in {"q", "quit", "zz"}:
            self.exit()
            return
        if c in {"?", "help"}:
            self.push_screen(HelpScreen())
            return
        if c.startswith(("set bg=", "set theme=")):
            theme = c.split("=", 1)[1].strip()
            mapping = {"mocha": "catppuccin-mocha", "latte": "catppuccin-latte"}
            if theme in mapping:
                self.theme = mapping[theme]
                self._set_hint(f"theme → {self.theme}")
            else:
                self._set_hint("E474: unknown theme")
            return
        view_aliases = {
            "o": "overview",
            "overview": "overview",
            "d": "diff",
            "diff": "diff",
            "m": "migration",
            "migration": "migration",
            "a": "apply",
            "apply": "apply",
            "h": "history",
            "history": "history",
            "s": "settings",
            "settings": "settings",
            "config": "settings",
            "c": "connection",
            "conn": "connection",
            "connection": "connection",
        }
        if first in view_aliases:
            self.switch_view(view_aliases[first])
            self._set_hint(f":{first} — executed")
            return
        if c.startswith("apply"):
            self.switch_view("apply")
            self._set_hint(":apply — executed")
            return
        if c.startswith("rollback"):
            self.switch_view("history")
            self._set_hint("rollback queued — see history")
            return
        self._set_hint("E492: not an editor command")

    # ------------------------------------------------------------------ space chord + search

    def _focus_search(self) -> None:
        try:
            self.query_one("#sidebar-search", Input).focus()
        except Exception:
            return

    def _resolve_space_chord(self, _key: str) -> None:
        if self._active_view != "diff":
            self._set_hint("(space leader — open Diff first)")
            return
        self._set_hint("(chord cancelled)")

    # ------------------------------------------------------------------ navigation messages

    def on_diff_requested(self, message: DiffRequested) -> None:
        self.query_one("#diff", DiffView).delta_id = message.delta_id
        self.switch_view("diff")
        self._set_hint(f"diff → {message.delta_id}")
        message.stop()

    def on_ai_requested(self, message: AiRequested) -> None:
        self.push_screen(AiModal(ai_for(message.target)))
        message.stop()

    def on_apply_requested(self, message: ApplyRequested) -> None:
        self.switch_view("apply")
        self._set_hint(":apply — opened")
        message.stop()


def run() -> None:
    """Launch the TUI (used by ``pgsd tui`` and ``pgsd``)."""
    PgsdApp().run()


if __name__ == "__main__":  # pragma: no cover
    run()
