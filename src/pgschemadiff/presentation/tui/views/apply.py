"""Apply view (``ga``) — pre-flight checklist, progress worker, live log."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rich.markup import escape
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Log, ProgressBar, Static
from textual.worker import Worker, get_current_worker

from pgschemadiff.presentation.tui._mock import APPLY_STEPS, PREFLIGHT
from pgschemadiff.presentation.tui.views._common import Panel, SectionHeader

if TYPE_CHECKING:
    from textual import events
    from textual.app import ComposeResult

# Seconds between simulated steps — small so the demo (and tests) move quickly.
_STEP_DELAY = 0.05
_SEV_COLOUR = {"ok": "$success", "warn": "$warning", "err": "$error", "info": "$secondary"}


class ApplyView(Widget):
    """Confirm → run → success/failed lifecycle with a streaming log."""

    phase: reactive[str] = reactive("confirm")
    dry_run: reactive[bool] = reactive(True)

    _worker_ref: Worker[None] | None = None

    DEFAULT_CSS = """
    ApplyView { height: 1fr; }
    ApplyView > VerticalScroll { height: 1fr; padding: 1 2; }
    ApplyView .toolbar { height: 1; margin-bottom: 1; }
    ApplyView .action { padding: 0 1; margin-left: 1; background: $boost; color: $text; }
    ApplyView .action.primary { background: $primary; color: $background; text-style: bold; }
    ApplyView .action.danger { background: $error; color: $background; text-style: bold; }
    ApplyView .action:hover { background: $surface-lighten-1; }
    ApplyView .pf-item { padding: 0 1; height: 1; }
    ApplyView #steps { height: auto; padding: 1 0; color: $text-muted; }
    ApplyView Log { height: 16; background: $panel; border: round $surface-lighten-1; }

    /* phase-driven visibility */
    ApplyView #pf-panel, ApplyView #progress-panel, ApplyView #log-panel { display: none; }
    ApplyView.confirm #pf-panel { display: block; }
    ApplyView.running #progress-panel, ApplyView.running #log-panel { display: block; }
    ApplyView.success #progress-panel, ApplyView.success #log-panel { display: block; }
    ApplyView.failed #progress-panel, ApplyView.failed #log-panel { display: block; }

    ApplyView #btn-run { display: none; }
    ApplyView #btn-abort { display: none; }
    ApplyView #btn-new { display: none; }
    ApplyView.confirm #btn-run { display: block; }
    ApplyView.confirm #btn-dry { display: block; }
    ApplyView.running #btn-abort { display: block; }
    ApplyView.success #btn-new { display: block; }
    ApplyView.failed #btn-new { display: block; }
    """

    def compose(self) -> ComposeResult:
        yield SectionHeader("Apply migration", "→ acme_staging · 25 changes · est ~26 min")
        with VerticalScroll():
            with Horizontal(classes="toolbar"):
                yield Static("✓ dry-run", classes="action", id="btn-dry")
                yield Static("⏎ run dry-run", classes="action primary", id="btn-run")
                yield Static("⌘. abort & rollback", classes="action danger", id="btn-abort")
                yield Static("new run", classes="action primary", id="btn-new")
            with Panel("Pre-flight checklist", subtitle="AI verified", id="pf-panel"):
                for item in PREFLIGHT:
                    colour = _SEV_COLOUR[item.sev]
                    yield Static(
                        f"[{colour} bold]{item.glyph}[/] [$text]{escape(item.text)}[/]",
                        classes="pf-item",
                    )
                yield Static(
                    "\n[$text-muted]command preview:[/]  "
                    "[$primary]pgschemadiff apply --target acme_staging "
                    "--plan migration_20260523_142208.sql --auto-rollback-on-error[/]",
                    classes="pf-item",
                )
            with Panel("Progress", id="progress-panel"):
                yield ProgressBar(total=len(APPLY_STEPS), show_eta=False, id="apply-bar")
                yield Static(self._steps_markup(0), id="steps")
            with Vertical(id="log-panel"):
                yield Static("[$text-muted]tail -f migration.log[/]")
                yield Log(id="apply-log", highlight=False)

    # ------------------------------------------------------------- lifecycle

    def watch_phase(self, phase: str) -> None:
        for name in ("confirm", "running", "success", "failed"):
            self.set_class(name == phase, name)

    def watch_dry_run(self, value: bool) -> None:
        try:
            self.query_one("#btn-dry", Static).update("✓ dry-run" if value else "✗ dry-run")
            self.query_one("#btn-run", Static).update("⏎ run dry-run" if value else "⏎ apply now")
        except Exception:
            return

    def on_mount(self) -> None:
        self.phase = "confirm"

    @staticmethod
    def _steps_markup(done: int) -> str:
        cells = []
        for i in range(len(APPLY_STEPS)):
            if i < done:
                cells.append("[$success]▰[/]")
            elif i == done:
                cells.append("[$primary]▰[/]")
            else:
                cells.append("[$surface-lighten-1]▱[/]")
        return " ".join(cells)

    @staticmethod
    def _stamp(i: int) -> str:
        secs = 8 + i
        return f"14:22:{secs % 60:02d}"

    def _start(self) -> None:
        self.phase = "running"
        bar = self.query_one("#apply-bar", ProgressBar)
        bar.update(total=len(APPLY_STEPS), progress=0)
        log = self.query_one("#apply-log", Log)
        log.clear()
        target = "dry-run sandbox" if self.dry_run else "acme_staging"
        log.write_line(f"14:22:08 [info] connecting to {target} …")
        log.write_line("14:22:08 [ ok ] connected (postgres 16.2, ssl verify-full)")
        log.write_line("14:22:08 [info] BEGIN; SET lock_timeout='5s';")
        self._run_steps()

    def _run_steps(self) -> None:
        self._worker_ref = self.run_worker(self._worker(), exclusive=True, name="apply")

    async def _worker(self) -> None:
        worker = get_current_worker()
        log = self.query_one("#apply-log", Log)
        bar = self.query_one("#apply-bar", ProgressBar)
        steps = self.query_one("#steps", Static)
        for i, step in enumerate(APPLY_STEPS):
            if worker.is_cancelled:
                return
            steps.update(self._steps_markup(i))
            log.write_line(f"{self._stamp(i)} [info] [{step.id}] {step.label} …")
            await asyncio.sleep(_STEP_DELAY)
            note = (
                "warning: brief AccessExclusive lock" if step.kind == "warn" else "0 rows affected"
            )
            tag = "[warn]" if step.kind == "warn" else "[ ok ]"
            log.write_line(f"{self._stamp(i)} {tag}   ↳ done · {note}")
            bar.advance(1)
        steps.update(self._steps_markup(len(APPLY_STEPS)))
        log.write_line("14:22:30 [ ok ] ✓ migration complete · 18 steps · 0 errors")
        self.phase = "success"

    def _abort(self) -> None:
        if self._worker_ref is not None:
            self._worker_ref.cancel()
        log = self.query_one("#apply-log", Log)
        log.write_line("14:22:30 [ err] ✗ aborted by user · ROLLBACK; ✓ done")
        self.phase = "failed"

    def _reset(self) -> None:
        if self._worker_ref is not None:
            self._worker_ref.cancel()
        self.query_one("#apply-bar", ProgressBar).update(progress=0)
        self.query_one("#apply-log", Log).clear()
        self.query_one("#steps", Static).update(self._steps_markup(0))
        self.phase = "confirm"

    # ----------------------------------------------------------------- events

    def on_click(self, event: events.Click) -> None:
        wid = getattr(event.widget, "id", None) or ""
        if wid == "btn-dry":
            self.dry_run = not self.dry_run
        elif wid == "btn-run":
            self._start()
        elif wid == "btn-abort":
            self._abort()
        elif wid == "btn-new":
            self._reset()
