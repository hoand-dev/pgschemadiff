"""Custom Textual widgets used by the pgschemadiff TUI chrome."""

from pgschemadiff.presentation.tui.widgets.cmdbar import Cmdbar
from pgschemadiff.presentation.tui.widgets.header import HeaderBar
from pgschemadiff.presentation.tui.widgets.statusbar import Statusbar
from pgschemadiff.presentation.tui.widgets.tabs import TabActivated, TabSpec, ViewTabs

__all__ = ["Cmdbar", "HeaderBar", "Statusbar", "TabActivated", "TabSpec", "ViewTabs"]
