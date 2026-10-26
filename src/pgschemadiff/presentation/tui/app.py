"""The Textual application class — ``PgsdApp``.

Implements the vim-style chord dispatcher, theme cycling, command palette,
and screen composition described in ``docs/ui-design.md``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import psycopg_pool
from psycopg import Error as PsycopgError
from textual.app import App
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Button, ContentSwitcher, DataTable, Input

from pgschemadiff.application.migration.apply import (
    ApplyEvent,
    ApplyResult,
    apply_migration,
)
from pgschemadiff.application.migration.bundle import ValidatedBundle, load_bundle
from pgschemadiff.application.migration.generate import generate_migration
from pgschemadiff.application.migration.history import (
    MigrationHistoryUnavailableError,
    list_migration_history,
)
from pgschemadiff.application.migration.render import render_bundle
from pgschemadiff.application.sql_emit.risk import RiskLevel
from pgschemadiff.presentation.cli.commands.apply import _check_connectivity, _parse_timeout
from pgschemadiff.presentation.tui._mock import ai_for
from pgschemadiff.presentation.tui.screens import (
    AiModal,
    ConfirmApplyModal,
    HelpScreen,
    MainScreen,
)
from pgschemadiff.presentation.tui.session import TuiSession
from pgschemadiff.presentation.tui.views import ApplyView, DiffView, MigrationView
from pgschemadiff.presentation.tui.views.connection import (
    ConnectionView,
    ProfileSelected,
    TestBothRequested,
)
from pgschemadiff.presentation.tui.views.history import (
    HistoryRefreshRequested,
    HistoryRunSelected,
    HistoryView,
)
from pgschemadiff.presentation.tui.views.migration import (
    GenerateMigrationRequested,
    MigrationBundleWriteFailed,
    MigrationBundleWritten,
    MigrationGenerated,
    MigrationGenerationFailed,
    SaveBundleRequested,
)
from pgschemadiff.presentation.tui.widgets import (
    Cmdbar,
    HeaderBar,
    Statusbar,
    TabActivated,
    ViewTabs,
)
from pgschemadiff.shared.errors import (
    ApplyMigrationError,
    DiffError,
    InspectionError,
    RiskGateError,
)
from pgschemadiff.shared.logging import get_logger

if TYPE_CHECKING:
    from textual.events import Key
    from textual.worker import Worker

    from pgschemadiff.application.diff.compare_schemas import SchemaComparisonResult
    from pgschemadiff.application.migration.model import MigrationPlan
    from pgschemadiff.application.migration.history import MigrationHistoryRun
    from pgschemadiff.application.migration.ports import BundleReader
    from pgschemadiff.domain.models import Profile
    from pgschemadiff.presentation.composition import TuiDependencies
    from pgschemadiff.presentation.tui.views._common import (
        AiRequested,
        ApplyRequested,
        DiffRequested,
    )
    from pgschemadiff.presentation.tui.views.apply import (
        ApplyOperationRequested,
        CancelApplyRequested,
    )

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


def _read_and_validate_bundle(reader: BundleReader, path: Path) -> ValidatedBundle:
    manifest, up_sql = reader.read(path)
    return load_bundle(manifest, up_sql)


class ProfilesLoaded(Message):
    """Signal that profile state is ready for view refresh."""


class ComparisonCompleted(Message):
    """Signal that a successful comparison is stored in the session."""


class ComparisonFailed(Message):
    """Carry only a fixed, redacted comparison error message."""

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message


class ApplyBundleLoaded(Message):
    """Carry one validated saved bundle back to the UI loop."""

    def __init__(self, path: Path, bundle: ValidatedBundle) -> None:
        super().__init__()
        self.path = path
        self.bundle = bundle


class ApplyBundleLoadFailed(Message):
    """Signal a bundle read or validation error without its exception text."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path


class ApplyEventReceived(Message):
    """Forward one real applier event to the UI loop."""

    def __init__(self, event: ApplyEvent) -> None:
        super().__init__()
        self.event = event


class ApplyOperationFinished(Message):
    """Carry an apply/dry-run result or safe outcome to the UI loop."""

    def __init__(
        self,
        *,
        result: ApplyResult | None = None,
        error_message: str | None = None,
        cancelled: bool = False,
    ) -> None:
        super().__init__()
        self.result = result
        self.error_message = error_message
        self.cancelled = cancelled


class HistoryLoadFinished(Message):
    """Carry safe target history back to the UI loop."""

    def __init__(
        self,
        profile_token: int,
        *,
        runs: tuple[MigrationHistoryRun, ...] = (),
        status: str = "",
    ) -> None:
        super().__init__()
        self.profile_token = profile_token
        self.runs = runs
        self.status = status


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
        self._migration_generation_worker: Worker[None] | None = None
        self._bundle_load_worker: Worker[None] | None = None
        self._bundle_load_path: Path | None = None
        self._apply_worker: Worker[None] | None = None
        self._history_worker: Worker[None] | None = None
        self._history_io_lock = asyncio.Lock()
        self._pending_apply_request: tuple[Profile, ValidatedBundle, int, int] | None = None
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

    def _refresh_history_view(self) -> None:
        self.query_one("#history", HistoryView).update_from_session(self.session)

    def _cancel_history_worker(self) -> None:
        if self._history_worker is not None:
            self._history_worker.cancel()
            self._history_worker = None

    def _start_history_load(self) -> None:
        if self.session.apply_operation == "apply":
            self.session.history_status = "History refresh after apply."
            self._refresh_history_view()
            return

        profile = self.session.selected_profile
        dependencies = self.dependencies
        if profile is None:
            self._cancel_history_worker()
            self.session.clear_history()
            self.session.history_status = "No profile selected."
            self._refresh_history_view()
            return
        if dependencies is None:
            self.session.history_runs = ()
            self.session.history_status = "Could not load migration history."
            self._refresh_history_view()
            return

        self._cancel_history_worker()
        self.session.history_status = "Loading migration history…"
        self._refresh_history_view()
        self._history_worker = self.run_worker(
            self._read_history(profile, id(profile), dependencies),
            name="migration-history",
            # Own group: an exclusive shared read group would cancel a running comparison.
            group="history-read",
            exclusive=True,
        )

    async def _read_history(
        self,
        profile: Profile,
        profile_token: int,
        dependencies: TuiDependencies,
    ) -> None:
        try:
            async with self._history_io_lock:
                if self.session.apply_operation == "apply":
                    self.post_message(
                        HistoryLoadFinished(
                            profile_token,
                            status="History refresh after apply.",
                        )
                    )
                    return
                reader = dependencies.history_reader_factory(profile.target.dsn())
                runs = await list_migration_history(reader)
        except MigrationHistoryUnavailableError:
            self.post_message(
                HistoryLoadFinished(
                    profile_token,
                    status="History unavailable (incompatible layout).",
                )
            )
        except Exception:
            self.post_message(
                HistoryLoadFinished(profile_token, status="Could not load migration history.")
            )
        else:
            self.post_message(HistoryLoadFinished(profile_token, runs=runs))

    def on_history_load_finished(self, message: HistoryLoadFinished) -> None:
        profile = self.session.selected_profile
        if profile is None or id(profile) != message.profile_token:
            return
        self._history_worker = None
        self.session.history_runs = message.runs
        self.session.history_status = message.status or (
            "No migration history found." if not message.runs else ""
        )
        if self.session.selected_history_bundle_id is None and message.runs:
            self.session.selected_history_bundle_id = message.runs[0].bundle_id
        self._refresh_history_view()
        message.stop()

    def on_history_refresh_requested(self, message: HistoryRefreshRequested) -> None:
        self._start_history_load()
        message.stop()

    def on_history_run_selected(self, message: HistoryRunSelected) -> None:
        if any(run.bundle_id == message.bundle_id for run in self.session.history_runs):
            self.session.selected_history_bundle_id = message.bundle_id
            self._refresh_history_view()
        message.stop()

    def _start_test_both(self) -> None:
        if self.session.apply_operation in {"dry-run", "apply"}:
            return
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

        self._invalidate_migration()
        self._cancel_history_worker()
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
        cast("MainScreen", self.screen_stack[0]).update_from_session(self.session)

    def on_comparison_completed(self, _message: ComparisonCompleted) -> None:
        self._refresh_connection(status="Comparison complete.")
        cast("MainScreen", self.screen_stack[0]).update_from_session(self.session)
        self._refresh_migration_view()

    def on_comparison_failed(self, message: ComparisonFailed) -> None:
        self._report_comparison_error(message.message)
        cast("MainScreen", self.screen_stack[0]).update_from_session(self.session)
        self._refresh_migration_view()

    def on_profile_selected(self, message: ProfileSelected) -> None:
        if self.session.apply_operation in {"dry-run", "apply"}:
            return
        if not 0 <= message.index < len(self.session.profiles):
            return
        profile = self.session.profiles[message.index]
        if profile == self.session.selected_profile:
            return
        if self._comparison_worker is not None:
            self._comparison_worker.cancel()
            self._comparison_worker = None
        self._cancel_history_worker()
        self._cancel_bundle_load()
        self._cancel_migration_generation()
        self.session.select_profile(profile)
        self._refresh_connection()
        self._refresh_history_view()
        cast("MainScreen", self.screen_stack[0]).update_from_session(self.session)
        self._refresh_migration_view(status="", busy=False)
        self._refresh_apply_controls()

    def on_test_both_requested(self, _message: TestBothRequested) -> None:
        self._start_test_both()

    def action_test_both(self) -> None:
        self._start_test_both()

    def _cancel_migration_generation(self) -> None:
        if self._migration_generation_worker is not None:
            self._migration_generation_worker.cancel()
            self._migration_generation_worker = None

    def _invalidate_migration(self) -> None:
        self._cancel_bundle_load()
        self._cancel_migration_generation()
        self.session.clear_migration()
        self._refresh_migration_view(status="", busy=False)
        self._refresh_apply_controls()

    def _refresh_migration_view(
        self,
        *,
        status: str | None = None,
        busy: bool | None = None,
    ) -> None:
        view = self.query_one("#migration", MigrationView)
        view.update_from_session(self.session)
        if status is not None:
            view.status = status
        if busy is not None:
            view.busy = busy

    def on_generate_migration_requested(self, message: GenerateMigrationRequested) -> None:
        if self.session.apply_operation in {"dry-run", "apply"}:
            message.stop()
            return
        if not isinstance(message.max_risk, RiskLevel) or message.max_risk is RiskLevel.BLOCKED:
            self._refresh_migration_view(status="Could not generate migration bundle.", busy=False)
            message.stop()
            return
        comparison = self.session.last_comparison
        if comparison is None:
            self._refresh_migration_view(
                status="Compare schemas before generating a migration.",
                busy=False,
            )
            message.stop()
            return

        self._invalidate_migration()
        self._refresh_migration_view(status="Generating migration…", busy=True)
        self._migration_generation_worker = self.run_worker(
            self._generate_migration(comparison, message.max_risk),
            name="migration-generate",
            group="migration-generate",
            exclusive=True,
        )
        message.stop()

    async def _generate_migration(
        self,
        comparison: SchemaComparisonResult,
        max_risk: RiskLevel,
    ) -> None:
        try:
            plan = await asyncio.to_thread(
                generate_migration,
                comparison.deltas,
                max_risk=max_risk,
            )
            bundle = await asyncio.to_thread(render_bundle, plan)
        except RiskGateError as error:
            self.post_message(MigrationGenerationFailed(comparison, str(error)))
        except Exception:
            self.post_message(
                MigrationGenerationFailed(comparison, "Could not generate migration bundle.")
            )
        else:
            self.post_message(MigrationGenerated(comparison, plan, bundle))

    def on_migration_generated(self, message: MigrationGenerated) -> None:
        if self.session.last_comparison is not message.comparison:
            return
        self.session.migration_plan = message.plan
        self.session.rendered_bundle = message.bundle
        self.session.written_bundle_path = None
        self._refresh_migration_view(status="Migration generated.", busy=False)
        message.stop()

    def on_migration_generation_failed(self, message: MigrationGenerationFailed) -> None:
        if self.session.last_comparison is not message.comparison:
            return
        self._refresh_migration_view(status=message.message, busy=False)
        message.stop()

    def on_save_bundle_requested(self, message: SaveBundleRequested) -> None:
        if self.session.apply_operation in {"dry-run", "apply"}:
            message.stop()
            return
        plan = self.session.migration_plan
        output_dir = message.output_dir.strip()
        if plan is None or not output_dir or self.dependencies is None:
            self._refresh_migration_view(status="Could not save migration bundle.", busy=False)
            message.stop()
            return
        self._refresh_migration_view(status="Saving migration bundle…", busy=True)
        self.run_worker(
            self._write_migration_bundle(plan, Path(output_dir).expanduser()),
            name="migration-save",
            group="migration-save",
            exclusive=True,
        )
        message.stop()

    async def _write_migration_bundle(self, plan: MigrationPlan, output_dir: Path) -> None:
        dependencies = self.dependencies
        if dependencies is None:
            self.post_message(MigrationBundleWriteFailed(plan))
            return
        try:
            path = await asyncio.to_thread(
                dependencies.migration_writer.write,
                plan,
                output_dir,
            )
        except Exception:
            self.post_message(MigrationBundleWriteFailed(plan))
        else:
            self.post_message(MigrationBundleWritten(plan, path))

    def on_migration_bundle_written(self, message: MigrationBundleWritten) -> None:
        if self.session.migration_plan is not message.plan:
            return
        self._cancel_bundle_load()
        self.session.clear_apply()
        self.session.written_bundle_path = message.path
        self._refresh_migration_view(status="Migration bundle saved.", busy=False)
        if self._active_view == "apply":
            self._ensure_apply_bundle_loaded()
        message.stop()

    def on_migration_bundle_write_failed(self, message: MigrationBundleWriteFailed) -> None:
        if self.session.migration_plan is not message.plan:
            return
        self._refresh_migration_view(status="Could not save migration bundle.", busy=False)
        message.stop()

    # ---------------------------------------------------------------- apply

    def _cancel_bundle_load(self) -> None:
        if self._bundle_load_worker is not None:
            self._bundle_load_worker.cancel()
        self._bundle_load_worker = None
        self._bundle_load_path = None

    def _ensure_apply_bundle_loaded(self) -> None:
        path = self.session.written_bundle_path
        if path is None:
            self._cancel_bundle_load()
            self.session.clear_apply()
            self.session.apply_status = "Save a bundle in Migration before applying."
            self._refresh_apply_controls()
            return
        if self.session.validated_bundle is not None and self.session.validated_bundle_path == path:
            self._refresh_apply_controls()
            return
        if self._bundle_load_path == path and self._bundle_load_worker is not None:
            return

        self._cancel_bundle_load()
        self.session.validated_bundle = None
        self.session.validated_bundle_path = None
        self.session.apply_operation = "loading"
        self.session.apply_status = "Loading and validating bundle…"
        self._bundle_load_path = path
        self._refresh_apply_controls()
        self._bundle_load_worker = self.run_worker(
            self._load_apply_bundle(path),
            name="apply-bundle-load",
            group="apply-bundle-load",
            exclusive=True,
        )

    async def _load_apply_bundle(self, path: Path) -> None:
        dependencies = self.dependencies
        if dependencies is None:
            self.post_message(ApplyBundleLoadFailed(path))
            return
        try:
            bundle = await asyncio.to_thread(
                _read_and_validate_bundle,
                dependencies.bundle_reader,
                path,
            )
        except Exception:
            self.post_message(ApplyBundleLoadFailed(path))
        else:
            self.post_message(ApplyBundleLoaded(path, bundle))

    def on_apply_bundle_loaded(self, message: ApplyBundleLoaded) -> None:
        if self._bundle_load_path != message.path:
            return
        self._bundle_load_worker = None
        self._bundle_load_path = None
        if self.session.written_bundle_path != message.path:
            return
        self.session.validated_bundle = message.bundle
        self.session.validated_bundle_path = message.path
        self.session.apply_operation = None
        self.session.apply_status = "Bundle validated."
        self._refresh_apply_controls()
        message.stop()

    def on_apply_bundle_load_failed(self, message: ApplyBundleLoadFailed) -> None:
        if self._bundle_load_path != message.path:
            return
        self._bundle_load_worker = None
        self._bundle_load_path = None
        if self.session.written_bundle_path != message.path:
            return
        self.session.validated_bundle = None
        self.session.validated_bundle_path = None
        self.session.apply_operation = None
        self.session.apply_status = "Could not load migration bundle."
        self._refresh_apply_controls()
        message.stop()

    def _refresh_apply_controls(self) -> None:
        apply_view = self.query_one("#apply", ApplyView)
        apply_view.update_from_session(self.session)
        busy = self.session.apply_operation in {"dry-run", "apply"}
        self.query_one("#saved-profiles", DataTable).disabled = busy
        self.query_one("#btn-test-both", Button).disabled = (
            busy or self.session.selected_profile is None
        )
        migration = self.query_one("#migration", MigrationView)
        self.query_one("#mig-generate", Button).disabled = (
            busy or self.session.last_comparison is None or migration.busy
        )
        self.query_one("#mig-save", Button).disabled = (
            busy or self.session.migration_plan is None or migration.busy
        )
        self.query_one("#mig-apply", Button).disabled = (
            busy or self.session.written_bundle_path is None or migration.busy
        )

    def on_apply_operation_requested(self, message: ApplyOperationRequested) -> None:
        if self.session.apply_operation in {"loading", "dry-run", "apply"}:
            message.stop()
            return
        profile = self.session.selected_profile
        bundle = self.session.validated_bundle
        if (
            profile is None
            or bundle is None
            or self.session.validated_bundle_path != self.session.written_bundle_path
        ):
            self.session.apply_status = "Could not load migration bundle."
            self._refresh_apply_controls()
            message.stop()
            return

        try:
            lock_timeout_ms = _parse_timeout(message.lock_timeout, "--lock-timeout")
            statement_timeout_ms = _parse_timeout(
                message.statement_timeout,
                "--statement-timeout",
            )
        except ValueError as error:
            self.session.apply_status = str(error)
            self._refresh_apply_controls()
            message.stop()
            return

        if message.dry_run:
            if any(unit.max_risk is RiskLevel.BLOCKED for unit in bundle.units):
                self.session.apply_status = (
                    "Migration bundle contains a BLOCKED unit and cannot be applied."
                )
                self._refresh_apply_controls()
                message.stop()
                return
            self._start_apply_worker(
                profile,
                bundle,
                lock_timeout_ms=lock_timeout_ms,
                statement_timeout_ms=statement_timeout_ms,
                dry_run=True,
                approve_destructive=False,
            )
        else:
            self._pending_apply_request = (
                profile,
                bundle,
                lock_timeout_ms,
                statement_timeout_ms,
            )
            self.push_screen(
                ConfirmApplyModal(profile, bundle),
                callback=self._on_apply_confirmation,
            )
        message.stop()

    def _on_apply_confirmation(self, confirmed: bool | None) -> None:
        request = self._pending_apply_request
        self._pending_apply_request = None
        if confirmed is not True or request is None:
            return
        profile, bundle, lock_timeout_ms, statement_timeout_ms = request
        if (
            profile != self.session.selected_profile
            or bundle is not self.session.validated_bundle
            or self.session.validated_bundle_path != self.session.written_bundle_path
        ):
            return
        if any(unit.max_risk is RiskLevel.BLOCKED for unit in bundle.units):
            self.session.apply_status = (
                "Migration bundle contains a BLOCKED unit and cannot be applied."
            )
            self._refresh_apply_controls()
            return
        destructive = any(unit.max_risk is RiskLevel.DESTRUCTIVE for unit in bundle.units)
        self._start_apply_worker(
            profile,
            bundle,
            lock_timeout_ms=lock_timeout_ms,
            statement_timeout_ms=statement_timeout_ms,
            dry_run=False,
            approve_destructive=destructive,
        )

    def _start_apply_worker(
        self,
        profile: Profile,
        bundle: ValidatedBundle,
        *,
        lock_timeout_ms: int,
        statement_timeout_ms: int,
        dry_run: bool,
        approve_destructive: bool,
    ) -> None:
        if not dry_run:
            self._cancel_history_worker()
            self.session.history_status = "History refresh after apply."
            self._refresh_history_view()
        self.session.apply_events.clear()
        self.session.apply_event_timestamps.clear()
        self.session.apply_result = None
        self.session.apply_operation = "dry-run" if dry_run else "apply"
        self.session.apply_status = (
            "Checking target connectivity…" if dry_run else "Applying migration bundle…"
        )
        self._refresh_apply_controls()
        self._apply_worker = self.run_worker(
            self._run_apply_operation(
                profile,
                bundle,
                lock_timeout_ms=lock_timeout_ms,
                statement_timeout_ms=statement_timeout_ms,
                dry_run=dry_run,
                approve_destructive=approve_destructive,
            ),
            name="apply",
            group="apply",
            exclusive=True,
        )

    async def _run_apply_operation(
        self,
        profile: Profile,
        bundle: ValidatedBundle,
        *,
        lock_timeout_ms: int,
        statement_timeout_ms: int,
        dry_run: bool,
        approve_destructive: bool,
    ) -> None:
        try:
            if dry_run:
                await _check_connectivity(profile.target.dsn())
            else:
                dependencies = self.dependencies
                if dependencies is None:
                    raise RuntimeError

                def forward_event(event: ApplyEvent) -> None:
                    self.post_message(ApplyEventReceived(event))

                async with self._history_io_lock:
                    async with dependencies.executor_factory(
                        profile.target.dsn(),
                        lock_timeout_ms=lock_timeout_ms,
                        statement_timeout_ms=statement_timeout_ms,
                    ) as executor:
                        result = await apply_migration(
                            bundle,
                            executor,
                            approve_destructive=approve_destructive,
                            on_event=forward_event,
                        )
                self.post_message(ApplyOperationFinished(result=result))
                return
        except asyncio.CancelledError:
            self.post_message(ApplyOperationFinished(cancelled=True))
            raise
        except (PsycopgError, psycopg_pool.PoolTimeout):
            self.post_message(ApplyOperationFinished(error_message="Database connection failed."))
        except RiskGateError as error:
            self.post_message(ApplyOperationFinished(error_message=str(error)))
        except ApplyMigrationError as error:
            failure_result = error.result if isinstance(error.result, ApplyResult) else None
            self.post_message(
                ApplyOperationFinished(
                    result=failure_result,
                    error_message="Migration apply failed.",
                )
            )
        except Exception:
            self.post_message(ApplyOperationFinished(error_message="Migration apply failed."))
        else:
            self.post_message(ApplyOperationFinished())

    def on_apply_event_received(self, message: ApplyEventReceived) -> None:
        if self.session.apply_operation != "apply":
            return
        self.session.apply_events.append(message.event)
        self.session.apply_event_timestamps.append(datetime.now().astimezone().strftime("%H:%M:%S"))
        self._refresh_apply_controls()
        message.stop()

    def on_apply_operation_finished(self, message: ApplyOperationFinished) -> None:
        operation = self.session.apply_operation
        self._apply_worker = None
        self.session.apply_operation = None
        self.session.apply_result = message.result
        if message.cancelled:
            self.session.apply_status = (
                "Cancelled — earlier units remain applied; an in-flight non-transactional "
                "statement may be indeterminate."
                if operation == "apply"
                else "Dry-run cancelled."
            )
        elif message.error_message is not None:
            self.session.apply_status = message.error_message
        elif operation == "dry-run":
            self.session.apply_status = (
                "Dry-run connectivity check passed; no migration SQL or history was touched."
            )
        else:
            self.session.apply_status = "Migration apply finished."
        self._refresh_apply_controls()
        if operation == "apply":
            self._start_history_load()
        message.stop()

    def on_cancel_apply_requested(self, message: CancelApplyRequested) -> None:
        if self.session.apply_operation == "apply" and self._apply_worker is not None:
            self._apply_worker.cancel()
        message.stop()

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
        if view_id == "apply":
            self._ensure_apply_bundle_loaded()
        elif view_id == "history":
            self._start_history_load()

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
            self._handle_g_chord(event)
            return
        if self._chord == "Z":
            self._chord = None
            if (event.character or event.key) == "Z":
                self._set_hint("ZZ — bye")
                self.exit()
                event.stop()
                return
            self._set_hint("(chord cancelled)")

    def _handle_g_chord(self, event: Key) -> None:
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
        if first == "rollback":
            parts = cmd.strip().split(maxsplit=1)
            if len(parts) > 1 and parts[1].strip():
                self.session.selected_history_bundle_id = parts[1].strip()
            self.switch_view("history")
            self._set_hint("Rollback is not available; down.sql is notes only.")
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
