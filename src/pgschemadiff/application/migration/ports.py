"""Output ports for migration application use cases."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from pgschemadiff.application.migration.model import MigrationPlan


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
