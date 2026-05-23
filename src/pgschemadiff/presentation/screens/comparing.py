"""ComparingScreen — async worker + progress bar for schema comparison."""

from __future__ import annotations

import asyncio

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, ProgressBar, RichLog, Static

from pgschemadiff.domain.models import Profile

# Steps shown while comparing; each is (target_progress, status_message).
_STEPS: list[tuple[int, str]] = [
    (10, "Connecting to source database…"),
    (20, "Connecting to target database…"),
    (40, "Inspecting source schema…"),
    (60, "Inspecting target schema…"),
    (75, "Running diff algorithm…"),
    (90, "Generating migration SQL…"),
    (100, "Comparison complete."),
]


class ComparingScreen(Screen):
    """Loading screen shown while async schema comparison is running."""

    BINDINGS = [
        Binding("escape", "cancel_compare", "Cancel", show=True),
    ]

    def __init__(self, profile: Profile) -> None:
        super().__init__()
        self._profile = profile

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="comparing-container"):
            yield Static(
                f"[bold]Comparing:[/] {self._profile.name}",
                id="comparing-title",
            )
            yield Static(
                f"[#6c7086]{self._profile.source.display()}[/]"
                f"[#cdd6f4] → [/]"
                f"[#6c7086]{self._profile.target.display()}[/]",
                id="comparing-subtitle",
            )
            yield ProgressBar(total=100, show_eta=False, id="comparing-progress")
            yield Static("Initialising…", id="comparing-status")
            yield RichLog(id="comparing-log", max_lines=30, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "pgschemadiff"
        self.sub_title = f"Comparing · {self._profile.name}"
        self._run_comparison()

    @work(exclusive=True)
    async def _run_comparison(self) -> None:
        """Async worker that steps through comparison stages."""
        bar = self.query_one("#comparing-progress", ProgressBar)
        status = self.query_one("#comparing-status", Static)
        log = self.query_one("#comparing-log", RichLog)

        try:
            for target_pct, message in _STEPS:
                await asyncio.sleep(0.55)
                bar.progress = target_pct
                status.update(message)
                log.write(
                    f"[#6c7086][[/][#89b4fa]{target_pct:>3}%[/][#6c7086]][/] {message}"
                )

            await asyncio.sleep(0.5)
            self.app.pop_screen()
            self.app.notify(
                f"'{self._profile.name}' schema comparison finished.",
                title="Compare done",
                severity="information",
            )
        except asyncio.CancelledError:
            status.update("[#f38ba8]Cancelled.[/]")
            log.write("[#f38ba8]Comparison cancelled by user.[/]")

    def action_cancel_compare(self) -> None:
        self.workers.cancel_all()
        self.app.pop_screen()
