"""Placeholder views for the 7 TUI screens.

Each is a thin shell that renders the section's intent + a "wired in Phase X"
note. The full implementations land in tasks ``P4-TUI-02`` … ``P4-TUI-08``
once the corresponding ``application/`` use cases exist.
"""

from pgschemadiff.presentation.tui.views.placeholders import (
    ApplyView,
    ConnectionView,
    DiffView,
    HistoryView,
    MigrationView,
    OverviewView,
    SettingsView,
)

__all__ = [
    "ApplyView",
    "ConnectionView",
    "DiffView",
    "HistoryView",
    "MigrationView",
    "OverviewView",
    "SettingsView",
]
