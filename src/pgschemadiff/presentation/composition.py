"""Shared composition for supported presentation entry points."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from pgschemadiff.application.diff.compare_schemas import (
    SchemaComparisonResult,
    compare_schemas_with_snapshots,
)
from pgschemadiff.infrastructure.config.yaml_loader import ProfileLoader
from pgschemadiff.infrastructure.fs.bundle_reader import FilesystemBundleReader
from pgschemadiff.infrastructure.fs.migration_writer import FilesystemMigrationWriter
from pgschemadiff.infrastructure.postgres.applier import open_executor
from pgschemadiff.infrastructure.postgres.inspector import PgCatalogInspector
from pgschemadiff.infrastructure.postgres.pool import Pool

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from contextlib import AbstractAsyncContextManager

    from pgschemadiff.application.diff.renames import RenameAnnotations
    from pgschemadiff.application.migration.ports import (
        BundleReader,
        MigrationExecutor,
        MigrationWriter,
    )

_POOL_OPEN_TIMEOUT = 5.0
CompareCallable = Callable[[str, str, list[str] | None], Awaitable[SchemaComparisonResult]]


class InspectorScope(Protocol):
    """Factory for opening source and target catalog inspectors."""

    def __call__(
        self,
        source_conninfo: str,
        target_conninfo: str,
        *,
        schemas: list[str] | None = None,
    ) -> AbstractAsyncContextManager[tuple[PgCatalogInspector, PgCatalogInspector]]: ...


class ExecutorFactory(Protocol):
    """Factory for the configured migration executor scope."""

    def __call__(
        self,
        conninfo: str,
        *,
        lock_timeout_ms: int = 5_000,
        statement_timeout_ms: int = 0,
    ) -> AbstractAsyncContextManager[MigrationExecutor]: ...


@dataclass(frozen=True)
class TuiDependencies:
    """Infrastructure dependencies supplied to the Textual app."""

    profile_loader: ProfileLoader
    inspector_scope: InspectorScope
    migration_writer: MigrationWriter
    bundle_reader: BundleReader
    executor_factory: ExecutorFactory
    compare: CompareCallable = field(default_factory=lambda: compare_conninfo)


def resolve_profile_path(config_path: Path | None = None) -> Path:
    """Resolve an explicit profile path or the supported default precedence."""
    if config_path is not None:
        return config_path

    configured = os.environ.get("PGSCHEMADIFF_CONFIG")
    if configured:
        return Path(configured).expanduser()

    local = Path.cwd() / "config" / "profiles.yaml"
    if local.exists():
        return local

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config_home) if xdg_config_home else Path.home() / ".config"
    return base / "pgschemadiff" / "profiles.yaml"


def create_profile_loader(config_path: Path | None = None) -> ProfileLoader:
    """Construct the profile loader for the resolved profile path."""
    return ProfileLoader(resolve_profile_path(config_path))


@asynccontextmanager
async def open_inspectors(
    source_conninfo: str,
    target_conninfo: str,
    *,
    schemas: list[str] | None = None,
) -> AsyncIterator[tuple[PgCatalogInspector, PgCatalogInspector]]:
    """Open both catalog inspectors using the CLI's pool timeout."""
    async with Pool(source_conninfo, open_timeout=_POOL_OPEN_TIMEOUT) as source_pool:
        source_inspector = PgCatalogInspector(source_pool, schemas=schemas)
        async with Pool(target_conninfo, open_timeout=_POOL_OPEN_TIMEOUT) as target_pool:
            target_inspector = PgCatalogInspector(target_pool, schemas=schemas)
            yield source_inspector, target_inspector


async def compare_conninfo(
    source_conninfo: str,
    target_conninfo: str,
    schemas: list[str] | None = None,
    *,
    renames: RenameAnnotations | None = None,
) -> SchemaComparisonResult:
    """Compare two connections and retain both inspected database snapshots."""
    async with open_inspectors(source_conninfo, target_conninfo, schemas=schemas) as (
        source_inspector,
        target_inspector,
    ):
        return await compare_schemas_with_snapshots(
            source_inspector,
            target_inspector,
            renames=renames,
        )


def create_migration_writer() -> FilesystemMigrationWriter:
    """Construct the atomic filesystem migration writer."""
    return FilesystemMigrationWriter()


def create_bundle_reader() -> FilesystemBundleReader:
    """Construct the filesystem bundle reader."""
    return FilesystemBundleReader()


def create_executor(
    conninfo: str,
    *,
    lock_timeout_ms: int = 5_000,
    statement_timeout_ms: int = 0,
) -> AbstractAsyncContextManager[MigrationExecutor]:
    """Wrap the existing configured executor scope for dependency injection."""
    return open_executor(
        conninfo,
        lock_timeout_ms=lock_timeout_ms,
        statement_timeout_ms=statement_timeout_ms,
    )


def create_tui_dependencies(config_path: Path | None = None) -> TuiDependencies:
    """Construct TUI dependencies without opening PostgreSQL connections."""
    return TuiDependencies(
        profile_loader=create_profile_loader(config_path),
        inspector_scope=open_inspectors,
        migration_writer=create_migration_writer(),
        bundle_reader=create_bundle_reader(),
        executor_factory=create_executor,
    )
