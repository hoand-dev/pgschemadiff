from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Protocol, cast
from unittest.mock import Mock

import pytest
from psycopg import OperationalError
from psycopg_pool import PoolTimeout
from rich.text import Text
from textual.widgets import DataTable, Static

from pgschemadiff.application.diff.compare_schemas import SchemaComparisonResult
from pgschemadiff.domain.delta import DeltaSet
from pgschemadiff.domain.models import ConnectionInfo, Profile
from pgschemadiff.presentation.composition import TuiDependencies
from pgschemadiff.presentation.tui import PgsdApp
from pgschemadiff.presentation.tui.views.connection import ConnectionView
from pgschemadiff.shared.errors import DiffError, InspectionError

if TYPE_CHECKING:
    from pathlib import Path

    from structlog.stdlib import BoundLogger

    from pgschemadiff.application.migration.ports import BundleReader, MigrationWriter
    from pgschemadiff.domain.database import Database
    from pgschemadiff.infrastructure.config.yaml_loader import ProfileLoader
    from pgschemadiff.presentation.composition import (
        CompareCallable,
        ExecutorFactory,
        InspectorScope,
    )


class PilotLike(Protocol):
    async def pause(self, delay: float = 0.0) -> None: ...

    async def click(self, target: str) -> bool: ...


class FakeProfileLoader:
    def __init__(
        self,
        path: Path,
        profiles: list[Profile] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.config_path = path
        self.profiles = profiles or []
        self.error = error
        self.calls = 0
        self.thread_id: int | None = None

    def load(self) -> list[Profile]:
        self.calls += 1
        self.thread_id = threading.get_ident()
        if self.error is not None:
            raise self.error
        return self.profiles


class FakeSnapshot:
    def __init__(self, table_count: int) -> None:
        self._table_count = table_count
        self.schemas = ()
        self.extensions = ()

    def all_tables(self) -> tuple[object, ...]:
        return tuple(object() for _ in range(self._table_count))


def profile(
    name: str,
    *,
    password: str = "not-a-display-value",
    schemas: list[str] | None = None,
    mode: str = "schema-only",
) -> Profile:
    return Profile(
        name=name,
        source=ConnectionInfo(
            host=f"{name}-source.db",
            port=5433,
            database=f"{name}_source",
            user="reader",
            password=password,
        ),
        target=ConnectionInfo(
            host=f"{name}-target.db",
            port=5434,
            database=f"{name}_target",
            user="writer",
            password=password,
        ),
        schemas=[] if schemas is None else schemas,
        mode=mode,
    )


def comparison(source_tables: int = 3, target_tables: int = 4) -> SchemaComparisonResult:
    return SchemaComparisonResult(
        source=cast("Database", FakeSnapshot(source_tables)),
        target=cast("Database", FakeSnapshot(target_tables)),
        deltas=DeltaSet(),
    )


def dependencies(
    profiles: list[Profile],
    *,
    path: Path,
    compare: CompareCallable | None = None,
    load_error: Exception | None = None,
) -> tuple[TuiDependencies, FakeProfileLoader]:
    async def no_compare(
        _source: str, _target: str, _schemas: list[str] | None
    ) -> SchemaComparisonResult:
        return comparison()

    loader = FakeProfileLoader(path, profiles, load_error)
    return (
        TuiDependencies(
            profile_loader=cast("ProfileLoader", loader),
            inspector_scope=cast("InspectorScope", Mock()),
            migration_writer=cast("MigrationWriter", Mock()),
            bundle_reader=cast("BundleReader", Mock()),
            executor_factory=cast("ExecutorFactory", Mock()),
            compare=no_compare if compare is None else compare,
        ),
        loader,
    )


def plain(app: PgsdApp, selector: str) -> str:
    rendered = app.query_one(selector, Static).render()
    return rendered.plain if isinstance(rendered, Text) else str(rendered)


def rendered_statics(app: PgsdApp) -> str:
    values = []
    for widget in app.query(Static):
        rendered = widget.render()
        values.append(rendered.plain if isinstance(rendered, Text) else str(rendered))
    return "\n".join(values)


def rendered_connection_statics(app: PgsdApp) -> str:
    view = app.query_one("#connection", ConnectionView)
    values = []
    for widget in view.query(Static):
        rendered = widget.render()
        values.append(rendered.plain if isinstance(rendered, Text) else str(rendered))
    return "\n".join(values)


async def wait_for_workers(app: PgsdApp, pilot: PilotLike) -> None:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def run_test_both(app: PgsdApp, pilot: PilotLike) -> None:
    app.switch_view("connection")
    await pilot.pause()
    await pilot.click("#btn-test-both")
    await app.workers.wait_for_complete()
    await pilot.pause()


@pytest.mark.unit
async def test_connection_view_renders_real_profiles_and_safe_fields(tmp_path: Path) -> None:
    saved = [profile("production"), profile("staging")]
    deps, loader = dependencies(saved, path=tmp_path / "profiles.yaml")
    app = PgsdApp(dependencies=deps)

    async with app.run_test(size=(140, 44)) as pilot:
        await wait_for_workers(app, pilot)

        source = plain(app, "#connection-source")
        target = plain(app, "#connection-target")
        rows = app.query_one("#saved-profiles", DataTable)
        assert "production" in source
        assert "production-source.db" in source
        assert "5433" in source
        assert "production_source" in source
        assert "reader" in source
        assert "schemas" in source
        assert "n/a" in source
        assert "production-target.db" in target
        assert rows.row_count == 2
        assert "production" in str(rows.get_row_at(0)[0])
        assert "current" in str(rows.get_row_at(0)[2])
        assert "last used" not in plain(app, "#connection-options").lower()
        assert "owner roles" not in plain(app, "#connection-options").lower()
        assert "include data" not in plain(app, "#connection-options").lower()
        assert "save profile" not in rendered_connection_statics(app).lower()

    assert loader.calls == 1
    assert loader.thread_id != threading.get_ident()


@pytest.mark.unit
async def test_connection_view_empty_profiles_shows_config_path(tmp_path: Path) -> None:
    path = tmp_path / "profiles.yaml"
    deps, _ = dependencies([], path=path)
    app = PgsdApp(dependencies=deps)

    async with app.run_test(size=(140, 44)) as pilot:
        await wait_for_workers(app, pilot)
        empty = plain(app, "#connection-empty")

        assert "no profiles" in empty.lower()
        assert str(path) in empty


@pytest.mark.unit
async def test_profile_load_error_is_generic_and_redacted(tmp_path: Path) -> None:
    deps, _ = dependencies(
        [], path=tmp_path / "profiles.yaml", load_error=ValueError("password-load-sentinel")
    )
    app = PgsdApp(dependencies=deps)

    async with app.run_test(size=(140, 44)) as pilot:
        await wait_for_workers(app, pilot)
        status = plain(app, "#connection-status")

        assert status == "Could not load profiles."
        assert "password-load-sentinel" not in status


@pytest.mark.unit
async def test_test_both_stores_comparison_and_renders_snapshot_table_counts(
    tmp_path: Path,
) -> None:
    selected = profile("selected", schemas=[])
    result = comparison(2, 5)
    calls: list[tuple[str, str, list[str] | None]] = []

    async def compare(
        source: str, target: str, schemas: list[str] | None
    ) -> SchemaComparisonResult:
        calls.append((source, target, schemas))
        return result

    deps, _ = dependencies([selected], path=tmp_path / "profiles.yaml", compare=compare)
    app = PgsdApp(dependencies=deps)

    async with app.run_test(size=(140, 44)) as pilot:
        await wait_for_workers(app, pilot)
        await run_test_both(app, pilot)

        assert app.session.last_comparison is result
        assert "2" in plain(app, "#connection-source")
        assert "5" in plain(app, "#connection-target")
        assert plain(app, "#connection-status") == "Comparison complete."

    assert calls == [(selected.source.dsn(), selected.target.dsn(), None)]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error", "message"),
    [
        (OperationalError("connection secret"), "Could not connect to one or both databases."),
        (PoolTimeout("pool timeout"), "Could not connect to one or both databases."),
        (InspectionError("inspection secret"), "Could not inspect database schemas."),
        (DiffError("comparison secret"), "Could not compare database schemas."),
        (RuntimeError("unknown secret"), "Comparison failed."),
    ],
)
async def test_test_both_maps_failures_to_generic_messages(
    tmp_path: Path, error: Exception, message: str
) -> None:
    async def compare(
        _source: str, _target: str, _schemas: list[str] | None
    ) -> SchemaComparisonResult:
        raise error

    deps, _ = dependencies([profile("selected")], path=tmp_path / "profiles.yaml", compare=compare)
    app = PgsdApp(dependencies=deps)

    async with app.run_test(size=(140, 44)) as pilot:
        await wait_for_workers(app, pilot)
        await run_test_both(app, pilot)

        assert plain(app, "#connection-status") == message
        assert app.session.last_comparison is None


@pytest.mark.unit
async def test_ignore_patterns_block_comparison_before_connection(tmp_path: Path) -> None:
    calls = 0

    async def compare(
        _source: str, _target: str, _schemas: list[str] | None
    ) -> SchemaComparisonResult:
        nonlocal calls
        calls += 1
        return comparison()

    selected = profile("selected").model_copy(update={"ignore_patterns": ["private.*"]})
    deps, _ = dependencies([selected], path=tmp_path / "profiles.yaml", compare=compare)
    app = PgsdApp(dependencies=deps)

    async with app.run_test(size=(140, 44)) as pilot:
        await wait_for_workers(app, pilot)
        await run_test_both(app, pilot)

        assert plain(app, "#connection-status") == "unsupported profile filters"

    assert calls == 0


@pytest.mark.unit
async def test_unsupported_profile_mode_blocks_comparison(tmp_path: Path) -> None:
    calls = 0

    async def compare(
        _source: str, _target: str, _schemas: list[str] | None
    ) -> SchemaComparisonResult:
        nonlocal calls
        calls += 1
        return comparison()

    deps, _ = dependencies(
        [profile("selected", mode="with-data")],
        path=tmp_path / "profiles.yaml",
        compare=compare,
    )
    app = PgsdApp(dependencies=deps)

    async with app.run_test(size=(140, 44)) as pilot:
        await wait_for_workers(app, pilot)
        await run_test_both(app, pilot)

        assert plain(app, "#connection-status") == "unsupported profile mode"

    assert calls == 0


@pytest.mark.unit
async def test_password_and_error_details_never_reach_ui_notifications_or_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    password = "PASSWORD_SENTINEL"
    error_host = "HOST_ERROR_SENTINEL"
    notifications: list[str] = []
    logs = Mock()

    async def compare(
        _source: str, _target: str, _schemas: list[str] | None
    ) -> SchemaComparisonResult:
        raise OperationalError(f"{error_host} {password}")

    deps, _ = dependencies(
        [profile("safe-profile", password=password)],
        path=tmp_path / "profiles.yaml",
        compare=compare,
    )
    app = PgsdApp(dependencies=deps)
    app._pgsd_logger = cast("BoundLogger", logs)

    def capture_notification(message: str, **_kwargs: object) -> None:
        notifications.append(message)

    monkeypatch.setattr(
        app,
        "notify",
        capture_notification,
    )

    async with app.run_test(size=(140, 44)) as pilot:
        await wait_for_workers(app, pilot)
        await run_test_both(app, pilot)
        app._dispatch_command(f"diff {password} {error_host}")
        await pilot.pause()

        rendered = rendered_statics(app)
        assert password not in rendered
        assert error_host not in rendered
        assert password not in "\n".join(notifications)
        assert error_host not in "\n".join(notifications)
        assert password not in repr(logs.mock_calls)
        assert error_host not in repr(logs.mock_calls)


@pytest.mark.unit
async def test_command_palette_logs_only_allowlisted_verb(tmp_path: Path) -> None:
    deps, _ = dependencies([], path=tmp_path / "profiles.yaml")
    app = PgsdApp(dependencies=deps)
    logger = Mock()
    app._pgsd_logger = cast("BoundLogger", logger)

    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app._dispatch_command("diff hidden-argument")

        assert logger.info.call_args.kwargs == {"command": "diff"}
        assert "hidden-argument" not in repr(logger.mock_calls)


@pytest.mark.unit
async def test_selecting_another_profile_invalidates_comparison(tmp_path: Path) -> None:
    first, second = profile("first"), profile("second")
    deps, _ = dependencies([first, second], path=tmp_path / "profiles.yaml")
    app = PgsdApp(dependencies=deps)

    async with app.run_test(size=(140, 44)) as pilot:
        await wait_for_workers(app, pilot)
        app.session.last_comparison = comparison()

        app.session.select_profile(second)

        assert app.session.selected_profile is second
        assert app.session.last_comparison is None


@pytest.mark.unit
async def test_bare_app_still_mounts_without_dependencies() -> None:
    app = PgsdApp()

    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()

        assert app.dependencies is None
        assert app.query_one("#connection")
