"""Connection view (``gc``) — source/target cards, compare options, profiles."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.markup import escape
from textual.containers import Horizontal, VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from pgschemadiff.presentation.tui._mock import (
    COMPARE_OPTIONS,
    SAVED_PROFILES,
    SOURCE,
    TARGET,
    ConnectionProfile,
)
from pgschemadiff.presentation.tui.views._common import Panel, SectionHeader

if TYPE_CHECKING:
    from textual.app import ComposeResult


def _card_lines(data: ConnectionProfile, *, role: str, accent: str) -> str:
    rows = (
        ("connection", data.url),
        ("host", data.host),
        ("database", data.database),
        ("schemas", data.schemas),
        ("role", data.role),
        ("ssl", data.ssl),
        ("version", data.version),
        ("latency", f"{data.latency_ms}ms"),
        ("tables", str(data.table_count)),
        ("size", data.size),
    )
    head = f"[{accent} bold]● {role.upper()}[/]  [$primary]{escape(data.label)}[/]"
    body = "\n".join(
        f"[$text-muted]{k:<11}[/] [{accent if k in {'connection', 'ssl'} else '$text'}]"
        f"{escape(v)}[/]"
        for k, v in rows
    )
    chips = "[$success on $boost] ● online [/]  " + f"[$text-muted on $boost] {data.size} [/]"
    if role == "target":
        chips += "  [$warning on $boost] +2 tables vs source [/]"
    return f"{head}\n\n{body}\n\n{chips}"


class ConnectionView(Widget):
    """Two side-by-side connection cards + compare options + saved profiles."""

    DEFAULT_CSS = """
    ConnectionView { height: 1fr; }
    ConnectionView > VerticalScroll { height: 1fr; padding: 1 2; }
    ConnectionView .cards { height: auto; }
    ConnectionView .cards Panel { width: 1fr; margin: 0 1 1 0; }
    ConnectionView .arrow { width: 5; content-align: center middle; color: $text-muted; }
    """

    def compose(self) -> ComposeResult:
        yield SectionHeader("Connections", "pgschemadiff · connection")
        with VerticalScroll():
            with Horizontal(classes="cards"):
                with Panel("● SOURCE", subtitle=SOURCE.label):
                    yield Static(_card_lines(SOURCE, role="source", accent="$secondary"))
                yield Static("→", classes="arrow")
                with Panel("● TARGET", subtitle=TARGET.label):
                    yield Static(_card_lines(TARGET, role="target", accent="$warning"))
            with Panel("Compare options", subtitle="--opts"):
                yield Static(self._options_markup())
            with Panel("Saved profiles", subtitle="~/.config/pgschemadiff/profiles.toml"):
                yield Static(self._profiles_markup())

    @staticmethod
    def _options_markup() -> str:
        lines = []
        for label, value, kind in COMPARE_OPTIONS:
            lines.append(
                f"[$text-muted]{label:<22}[/] [$text]{escape(value):<34}[/] "
                f"[$text-muted dim]{kind}[/]"
            )
        return "\n".join(lines)

    @staticmethod
    def _profiles_markup() -> str:
        header = (
            f"[$text-muted bold]{'name':<36}{'route':<34}{'last used':<12}{'owner':<12}default[/]"
        )
        rows = [header]
        for p in SAVED_PROFILES:
            mark = "[$success]✓ current[/]" if p.current else "[$text-muted]· switch[/]"
            name_colour = "$primary" if p.current else "$text"
            rows.append(
                f"[{name_colour}]{escape(p.name):<36}[/]"
                f"[$text-muted]{escape(p.route):<34}{p.last_used:<12}{p.owner:<12}[/]"
                f"{mark}"
            )
        return "\n".join(rows)
