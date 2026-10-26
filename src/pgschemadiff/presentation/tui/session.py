"""Current profile and comparison state for the Textual presentation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pgschemadiff.application.diff.compare_schemas import SchemaComparisonResult
    from pgschemadiff.domain.models import Profile


@dataclass
class TuiSession:
    """State shared by TUI views; contains no widgets or rendered markup."""

    profiles: tuple[Profile, ...] = ()
    selected_profile: Profile | None = None
    last_comparison: SchemaComparisonResult | None = None

    def set_profiles(self, profiles: list[Profile]) -> None:
        """Replace loaded profiles and select first entry when available."""
        self.profiles = tuple(profiles)
        self.select_profile(self.profiles[0] if self.profiles else None)

    def select_profile(self, profile: Profile | None) -> None:
        """Select a profile and discard comparison derived from another one."""
        if self.selected_profile != profile:
            self.selected_profile = profile
            self.last_comparison = None
