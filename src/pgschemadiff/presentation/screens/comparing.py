"""Comparing screen — async schema comparison with progress feedback."""

from __future__ import annotations

import asyncio

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ProgressBar, RichLog

from pgschemadiff.domain.models import Profile


class ComparingScreen(Screen):
    """Shows live progress while comparing two database schemas."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("q", "quit_app", "Quit", show=True),
    ]

    def __init__(self, profile: Profile) -> None:
        super().__init__()
        self._profile = profile

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="comparing-container"):
            yield Label(f"Comparing: {self._profile.name}", id="comparing-title")
            yield Label(
                f"  {self._profile.source.display()}  →  {self._profile.target.display()}",
                id="comparing-subtitle",
            )
            yield ProgressBar(total=100, show_eta=False, id="progress")
            yield RichLog(highlight=True, markup=True, id="log")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "pgschemadiff"
        self.sub_title = f"Comparing · {self._profile.name}"
        self._run_compare()

    @work(exclusive=True, thread=False)
    async def _run_compare(self) -> None:
        log = self.query_one(RichLog)
        bar = self.query_one(ProgressBar)

        steps: list[tuple[int, str]] = [
            (10, f"[bold #89b4fa]Connecting[/] to source: [#f9e2af]{self._profile.source.display()}[/]"),
            (20, f"[bold #89b4fa]Connecting[/] to target: [#f9e2af]{self._profile.target.display()}[/]"),
            (40, f"[bold #89b4fa]Inspecting[/] schemas: [#cdd6f4]{', '.join(self._profile.schemas)}[/]"),
            (60, "[bold #89b4fa]Comparing[/] tables, columns, constraints…"),
            (75, "[bold #89b4fa]Comparing[/] indexes, sequences, views…"),
            (90, "[bold #89b4fa]Comparing[/] functions, triggers, types…"),
            (100, "[bold #a6e3a1]Done.[/] Generating diff…"),
        ]

        for progress, message in steps:
            log.write(message)
            bar.update(progress=progress)
            await asyncio.sleep(0.4)

        log.write("")
        log.write("[bold #f9e2af]⚠  Database inspector not yet implemented.[/]")
        log.write("    This is a placeholder — real pg_catalog queries come next.")
        log.write("")
        log.write("Press [bold]Escape[/] to return to Home.")

    def action_cancel(self) -> None:
        self.workers.cancel_all()
        self.app.pop_screen()

    def action_quit_app(self) -> None:
        self.app.exit()
