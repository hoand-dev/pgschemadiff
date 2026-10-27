"""Plan helpers for integration tests that exercise the applier, not the source guard."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pgschemadiff.application.migration.generate import generate_migration

if TYPE_CHECKING:
    from pgschemadiff.application.migration.model import MigrationPlan
    from pgschemadiff.domain.delta import DeltaSet

# Format 2 bundles require fingerprints; these tests apply through the
# application layer, which does not run the presentation-level source guard.
SOURCE_FINGERPRINT = "sha256:" + "0" * 64
TARGET_FINGERPRINT = "sha256:" + "1" * 64


def generate_test_migration(delta_set: DeltaSet, **kwargs: Any) -> MigrationPlan:
    """Call ``generate_migration`` with fixed, valid placeholder fingerprints."""
    return generate_migration(
        delta_set,
        source_fingerprint=SOURCE_FINGERPRINT,
        target_fingerprint=TARGET_FINGERPRINT,
        **kwargs,
    )
