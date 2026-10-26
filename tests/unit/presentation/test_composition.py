from __future__ import annotations

from contextlib import asynccontextmanager
from inspect import signature
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from pgschemadiff.application.diff.renames import RenameAnnotations
from pgschemadiff.infrastructure.config.yaml_loader import ProfileLoader
from pgschemadiff.infrastructure.fs.bundle_reader import FilesystemBundleReader
from pgschemadiff.infrastructure.fs.migration_writer import FilesystemMigrationWriter
from pgschemadiff.infrastructure.postgres.inspector import PgCatalogInspector
from pgschemadiff.infrastructure.postgres.pool import Pool
from pgschemadiff.presentation import composition


def test_explicit_config_path_overrides_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PGSCHEMADIFF_CONFIG", str(tmp_path / "environment.yaml"))
    explicit = tmp_path / "explicit.yaml"

    assert composition.resolve_profile_path(explicit) == explicit


def test_environment_config_path_has_highest_default_precedence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    local = tmp_path / "config" / "profiles.yaml"
    local.parent.mkdir()
    local.touch()
    configured = tmp_path / "environment.yaml"
    monkeypatch.setenv("PGSCHEMADIFF_CONFIG", str(configured))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    assert composition.resolve_profile_path() == configured


def test_existing_working_directory_config_precedes_xdg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    local = tmp_path / "config" / "profiles.yaml"
    local.parent.mkdir()
    local.touch()
    monkeypatch.delenv("PGSCHEMADIFF_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    assert composition.resolve_profile_path() == local


def test_xdg_path_precedes_home_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PGSCHEMADIFF_CONFIG", raising=False)
    xdg_home = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path / "home"))

    assert composition.resolve_profile_path() == xdg_home / "pgschemadiff" / "profiles.yaml"


def test_home_config_is_final_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PGSCHEMADIFF_CONFIG", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))

    assert composition.resolve_profile_path() == home / ".config" / "pgschemadiff" / "profiles.yaml"


def test_dependency_factories_construct_without_database_io(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def unexpected_pool(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("pool must open only inside inspector scope")

    def unexpected_executor(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("executor must open only when its scope is entered")

    monkeypatch.setattr(composition, "Pool", unexpected_pool)
    monkeypatch.setattr(composition, "open_executor", unexpected_executor)

    dependencies = composition.create_tui_dependencies(tmp_path / "profiles.yaml")

    assert isinstance(dependencies.profile_loader, ProfileLoader)
    assert dependencies.profile_loader.config_path == tmp_path / "profiles.yaml"
    assert isinstance(composition.create_migration_writer(), FilesystemMigrationWriter)
    assert isinstance(composition.create_bundle_reader(), FilesystemBundleReader)


@pytest.mark.asyncio
async def test_inspector_scope_uses_two_lazy_pools_with_cli_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pools: list[FakePool] = []
    inspectors: list[FakeInspector] = []

    class FakePool(Pool):
        def __init__(self, conninfo: str, *, open_timeout: float) -> None:
            self.conninfo = conninfo
            self.open_timeout = open_timeout
            self.entered = False
            self.exited = False
            pools.append(self)

        async def __aenter__(self) -> FakePool:
            self.entered = True
            return self

        async def __aexit__(self, *_args: object) -> None:
            self.exited = True

    class FakeInspector(PgCatalogInspector):
        def __init__(self, pool: Pool, *, schemas: list[str] | None = None) -> None:
            self.pool = pool
            self.schemas = schemas
            inspectors.append(self)

    monkeypatch.setattr(composition, "Pool", FakePool)
    monkeypatch.setattr(composition, "PgCatalogInspector", FakeInspector)

    scope = composition.open_inspectors("source", "target", schemas=["app"])
    assert pools == []

    async with scope as pair:
        assert pair == tuple(inspectors)
        assert all(pool.entered for pool in pools)

    assert [(pool.conninfo, pool.open_timeout, pool.exited) for pool in pools] == [
        ("source", 5.0, True),
        ("target", 5.0, True),
    ]
    assert [inspector.schemas for inspector in inspectors] == [["app"], ["app"]]


@pytest.mark.asyncio
async def test_compare_conninfo_uses_inspector_scope_and_returns_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_inspector = object()
    target_inspector = object()
    inspectors = (source_inspector, target_inspector)
    sentinel = object()
    scope_calls: list[tuple[str, str, list[str] | None]] = []
    comparison_calls: list[tuple[object, object, object | None]] = []

    @asynccontextmanager
    async def fake_open_inspectors(
        source_conninfo: str,
        target_conninfo: str,
        *,
        schemas: list[str] | None = None,
    ) -> AsyncIterator[tuple[object, object]]:
        scope_calls.append((source_conninfo, target_conninfo, schemas))
        yield inspectors

    async def fake_compare(
        source: object,
        target: object,
        *,
        renames: object | None = None,
    ) -> object:
        comparison_calls.append((source, target, renames))
        return sentinel

    monkeypatch.setattr(composition, "open_inspectors", fake_open_inspectors)
    monkeypatch.setattr(composition, "compare_schemas_with_snapshots", fake_compare, raising=False)
    renames = RenameAnnotations()

    result = await composition.compare_conninfo("source", "target", ["app"], renames=renames)

    assert result is sentinel
    assert scope_calls == [("source", "target", ["app"])]
    assert comparison_calls == [(source_inspector, target_inspector, renames)]


@pytest.mark.asyncio
async def test_compare_conninfo_reports_inspection_phases_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert "on_phase" in signature(composition.compare_conninfo).parameters
    events: list[str] = []
    phases: list[str] = []

    class FakeInspector:
        def __init__(self, name: str) -> None:
            self.name = name

        async def inspect(self) -> object:
            events.append(f"{self.name}-inspect")
            return object()

    source_inspector = FakeInspector("source")
    target_inspector = FakeInspector("target")

    @asynccontextmanager
    async def fake_open_inspectors(
        _source_conninfo: str,
        _target_conninfo: str,
        *,
        schemas: list[str] | None = None,
    ) -> AsyncIterator[tuple[FakeInspector, FakeInspector]]:
        _ = schemas
        yield source_inspector, target_inspector

    async def fake_compare(
        source: FakeInspector,
        target: FakeInspector,
        *,
        renames: object | None = None,
    ) -> object:
        _ = renames
        await source.inspect()
        await target.inspect()
        events.append("comparison")
        return sentinel

    sentinel = object()
    monkeypatch.setattr(composition, "open_inspectors", fake_open_inspectors)
    monkeypatch.setattr(composition, "compare_schemas_with_snapshots", fake_compare)

    result = await composition.compare_conninfo(
        "source",
        "target",
        on_phase=phases.append,
    )

    assert result is sentinel
    assert phases == ["inspect-source", "inspect-target", "compare"]
    assert events == ["source-inspect", "target-inspect", "comparison"]


def test_executor_factory_wraps_open_executor_without_opening_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int, int]] = []
    context = object()

    def fake_open_executor(
        conninfo: str, *, lock_timeout_ms: int, statement_timeout_ms: int
    ) -> object:
        calls.append((conninfo, lock_timeout_ms, statement_timeout_ms))
        return context

    monkeypatch.setattr(composition, "open_executor", fake_open_executor)

    result = composition.create_executor(
        "target", lock_timeout_ms=1_500, statement_timeout_ms=2_500
    )

    assert result is context
    assert calls == [("target", 1_500, 2_500)]
