"""ComparingScreen — async loading screen with Worker + ProgressBar."""

from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ProgressBar, RichLog
from textual.worker import Worker, WorkerState

from pgschemadiff.domain.models import Profile

# Simulated steps: (progress_value, log_message)
_STEPS: list[tuple[int, str]] = [
    (10, "Resolving source host…"),
    (20, "Connecting to source database…"),
    (35, "Connecting to target database…"),
    (50, "Inspecting source schema (pg_catalog)…"),
    (70, "Inspecting target schema (pg_catalog)…"),
    (85, "Computing structural diff…"),
    (95, "Generating migration preview…"),
    (100, "Done."),
]


class ComparingScreen(Screen):
    """Loading screen: connect to both DBs, introspect schemas, compute diff."""

    BINDINGS = [
        Binding("escape", "abort", "Abort", show=True),
    ]

    def __init__(self, profile: Profile) -> None:
        super().__init__()
        self._profile = profile
        self._worker: Worker | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="comparing-body"):
            yield Label(
                f"[bold #89b4fa]Comparing:[/] [#f9e2af]{self._profile.name}[/]",
                id="comparing-title",
            )
            with Center():
                yield ProgressBar(
                    id="comparing-progress",
                    total=100,
                    show_eta=False,
                )
            yield Label("Starting…", id="comparing-status")
            yield RichLog(id="comparing-log", highlight=True, markup=True, min_width=60)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "pgschemadiff"
        self.sub_title = f"Comparing · {self._profile.name}"
        self._worker = self.run_worker(self._do_compare(), exclusive=True)

    async def _do_compare(self) -> None:
        bar = self.query_one(ProgressBar)
        status = self.query_one("#comparing-status", Label)
        log = self.query_one(RichLog)

        log.write(
            f"[#6c7086]Profile:[/]  [#cdd6f4]{self._profile.name}[/]\n"
            f"[#6c7086]Source: [/]  [#f9e2af]{self._profile.source.display()}[/]\n"
            f"[#6c7086]Target: [/]  [#f9e2af]{self._profile.target.display()}[/]\n"
            f"[#6c7086]Schemas:[/]  [#cdd6f4]{', '.join(self._profile.schemas)}[/]\n"
        )

        prev = 0
        for progress, message in _STEPS:
            status.update(message)
            log.write(f"[#89b4fa]→[/] {message}")
            bar.advance(progress - prev)
            prev = progress
            await asyncio.sleep(0.4)

        status.update("[#a6e3a1]Complete — press Esc to return[/]")
        log.write("\n[#a6e3a1]✓ Comparison complete.[/]")
        self.notify(
            f"Schema comparison for '{self._profile.name}' complete",
            title="Done",
            severity="information",
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.ERROR:
            err = str(event.worker.error)
            self.query_one("#comparing-status", Label).update(
                f"[#f38ba8]Error: {err}[/]"
            )
            self.query_one(RichLog).write(f"[#f38ba8]✗ Error: {err}[/]")
            self.notify(err, title="Comparison failed", severity="error")

    def action_abort(self) -> None:
        if self._worker and self._worker.state == WorkerState.RUNNING:
            self._worker.cancel()
        self.app.pop_screen()
