"""Current profile and comparison state for the Textual presentation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from pgschemadiff.application.diff.compare_schemas import SchemaComparisonResult
    from pgschemadiff.application.migration.model import MigrationPlan
    from pgschemadiff.application.migration.render import RenderedBundle
    from pgschemadiff.domain.models import Profile


@dataclass
class TuiSession:
    """State shared by TUI views; contains no widgets or rendered markup."""

    profiles: tuple[Profile, ...] = ()
    selected_profile: Profile | None = None
    last_comparison: SchemaComparisonResult | None = None
    migration_plan: MigrationPlan | None = None
    rendered_bundle: RenderedBundle | None = None
    written_bundle_path: Path | None = None

    def set_profiles(self, profiles: list[Profile]) -> None:
        """Replace loaded profiles and select first entry when available."""
        self.profiles = tuple(profiles)
        self.select_profile(self.profiles[0] if self.profiles else None)

    def select_profile(self, profile: Profile | None) -> None:
        """Select a profile and discard comparison derived from another one."""
        if self.selected_profile != profile:
            self.selected_profile = profile
            self.last_comparison = None
            self.clear_migration()

    def clear_migration(self) -> None:
        """Discard migration artifacts derived from the current comparison."""
        self.migration_plan = None
        self.rendered_bundle = None
        self.written_bundle_path = None
