"""Ports for migration application use cases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from pgschemadiff.application.migration.bundle import BundleUnit, ValidatedBundle
    from pgschemadiff.application.migration.history import MigrationHistoryRun
    from pgschemadiff.application.migration.model import MigrationPlan

RunStatus = Literal["running", "applied", "failed", "cancelled"]
RunFinishStatus = Literal["applied", "failed", "cancelled"]
UnitStatus = Literal["pending", "running", "applied", "failed"]
StatementObserver = Callable[[int, bool], None]


@dataclass(frozen=True)
class UnitHistory:
    """Persisted history metadata for one execution unit."""

    index: int
    sql_sha256: str
    transactional: bool
    status: UnitStatus


@dataclass(frozen=True)
class BundleHistory:
    """Persisted run and ordered unit state for one bundle."""

    status: RunStatus
    up_sql_sha256: str
    units: tuple[UnitHistory, ...]


@dataclass(frozen=True)
class UnitFailure:
    """Safe metadata for one SQL statement failure."""

    statement_index: int
    error_class: str
    sqlstate: str | None


@dataclass(frozen=True)
class RunFailure:
    """Safe run failure metadata persisted by an executor."""

    unit_index: int
    statement_index: int
    error_class: str
    sqlstate: str | None


@runtime_checkable
class BundleReader(Protocol):
    """Application port for reading the two files needed to validate a bundle."""

    def read(self, bundle_dir: Path) -> tuple[bytes, bytes]:
        """Return ``manifest.json`` and ``up.sql`` bytes, in that order."""
        ...


@runtime_checkable
class MigrationWriter(Protocol):
    """Application port for writing complete migration bundles.

    Implementations must publish bundles atomically and never overwrite an
    existing bundle.
    """

    def write(self, plan: MigrationPlan, output_dir: Path) -> Path:
        """Write a plan and return the created bundle directory.

        Raises
        ------
        pgschemadiff.shared.errors.MigrationError
            If an I/O operation fails.
        """
        ...


@runtime_checkable
class MigrationExecutor(Protocol):
    """Async execution/history port; adapter owns connection and advisory lock."""

    async def load_history(self, bundle_id: str) -> BundleHistory | None:
        """Return persisted run state, or ``None`` when no run exists."""
        ...

    async def start_run(self, bundle: ValidatedBundle, *, resume: bool) -> None:
        """Create pending history or mark an existing run as running."""
        ...

    async def apply_unit(
        self,
        bundle_id: str,
        unit: BundleUnit,
        on_statement: StatementObserver,
    ) -> UnitFailure | None:
        """Apply one unit and observe statement boundaries.

        Transactional DDL and its applied marker commit atomically. For a
        non-transactional unit, persist ``running`` before execution and
        ``applied`` immediately after success.
        """
        ...

    async def finish_run(
        self,
        bundle_id: str,
        status: RunFinishStatus,
        failure: RunFailure | None,
    ) -> None:
        """Persist final run status and safe failure metadata."""
        ...


@runtime_checkable
class MigrationHistoryReader(Protocol):
    """Read persisted migration history without changing target state."""

    async def list_history(self, *, limit: int = 50) -> tuple[MigrationHistoryRun, ...]:
        """Return at most ``limit`` runs, newest first, with ordered units."""
        ...
