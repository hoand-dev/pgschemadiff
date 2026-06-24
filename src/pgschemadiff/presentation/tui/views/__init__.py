"""The 7 TUI screens, wired to ``presentation/tui/_mock.py``.

Each view calls only into the mock data module (and, in future, the matching
``application/`` use case) — never directly into infrastructure.  This is the
deliverable of tasks ``P4-TUI-02`` … ``P4-TUI-08``.
"""

from pgschemadiff.presentation.tui.views.apply import ApplyView
from pgschemadiff.presentation.tui.views.connection import ConnectionView
from pgschemadiff.presentation.tui.views.diff import DiffView
from pgschemadiff.presentation.tui.views.history import HistoryView
from pgschemadiff.presentation.tui.views.migration import MigrationView
from pgschemadiff.presentation.tui.views.overview import OverviewView
from pgschemadiff.presentation.tui.views.settings import SettingsView

__all__ = [
    "ApplyView",
    "ConnectionView",
    "DiffView",
    "HistoryView",
    "MigrationView",
    "OverviewView",
    "SettingsView",
]
