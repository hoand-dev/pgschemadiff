"""Shared building blocks for the TUI views.

Provides a safe SQL syntax highlighter (returns Textual/Rich console markup),
small markup helpers for chips and diff lines, a reusable section header and a
bordered panel, plus the navigation :class:`~textual.message.Message` types the
views post up to :class:`~pgschemadiff.presentation.tui.app.PgsdApp`.
"""

from __future__ import annotations

import re

from rich.markup import escape
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static

# --------------------------------------------------------------------------- #
# Navigation messages (bubble up to PgsdApp)
# --------------------------------------------------------------------------- #


class DiffRequested(Message):
    """Open the Diff view for ``object_key`` (a key into ``_mock.DIFFS``)."""

    def __init__(self, object_key: str) -> None:
        super().__init__()
        self.object_key = object_key


class AiRequested(Message):
    """Open the AI suggestion modal for ``target`` (an object name)."""

    def __init__(self, target: str = "") -> None:
        super().__init__()
        self.target = target


class ApplyRequested(Message):
    """Switch to the Apply view (e.g. from the Migration view's apply button)."""


# --------------------------------------------------------------------------- #
# SQL syntax highlighter -> console markup
# --------------------------------------------------------------------------- #

_KEYWORDS = frozenset(
    {
        "begin",
        "commit",
        "rollback",
        "set",
        "create",
        "alter",
        "drop",
        "table",
        "type",
        "function",
        "trigger",
        "index",
        "unique",
        "primary",
        "key",
        "foreign",
        "references",
        "on",
        "delete",
        "cascade",
        "update",
        "add",
        "column",
        "using",
        "returns",
        "language",
        "as",
        "declare",
        "end",
        "for",
        "loop",
        "select",
        "from",
        "where",
        "and",
        "or",
        "null",
        "not",
        "default",
        "concurrently",
        "if",
        "exists",
        "value",
        "replace",
        "view",
        "enum",
        "check",
        "in",
        "case",
        "when",
        "then",
        "else",
        "execute",
        "each",
        "row",
        "after",
        "before",
        "insert",
        "into",
        "coalesce",
        "sum",
        "now",
        "gen_random_uuid",
        "lower",
        "constraint",
        "rename",
        "to",
        "of",
    }
)
_TYPES = frozenset(
    {
        "uuid",
        "text",
        "citext",
        "varchar",
        "bigint",
        "integer",
        "smallint",
        "numeric",
        "jsonb",
        "json",
        "timestamptz",
        "timestamp",
        "bytea",
        "bool",
        "boolean",
        "date",
        "interval",
        "plan_tier_enum",
        "task_priority",
        "subscription_status",
    }
)

# One pass: comment | string | word | number.  Order matters (comment first).
_TOKEN = re.compile(r"(--.*|'[^']*'|[A-Za-z_][A-Za-z0-9_]*|\d+)")


def _style_token(match: re.Match[str]) -> str:
    """Wrap a single (already markup-escaped) token in a colour tag."""
    tok = match.group(0)
    if tok.startswith("--"):
        return f"[$text-muted italic]{tok}[/]"
    if tok.startswith("'"):
        return f"[$success]{tok}[/]"
    low = tok.lower()
    if low in _KEYWORDS:
        return f"[$primary]{tok}[/]"
    if low in _TYPES:
        return f"[$secondary]{tok}[/]"
    if tok.isdigit():
        return f"[$warning]{tok}[/]"
    return tok


def sql_markup(line: str) -> str:
    """Return console markup for one line of SQL.

    The whole line is markup-escaped first, so any ``[`` / ``]`` in the SQL
    (e.g. ``-- [c01]`` migration comments) can never be mistaken for a tag.
    """
    return _TOKEN.sub(_style_token, escape(line))


# --------------------------------------------------------------------------- #
# Small markup helpers
# --------------------------------------------------------------------------- #

# Maps the design's op / risk / status vocabulary to a theme colour.
_OP_COLOUR = {
    "CREATE": "$success",
    "ALTER": "$warning",
    "REPLACE": "$warning",
    "DROP": "$error",
    "CONFLICT": "$warning",
}
_RISK_COLOUR = {
    "low": "$success",
    "medium": "$warning",
    "high": "$error",
    "conflict": "$warning",
}
_STATUS_GLYPH = {"add": "+", "mod": "~", "del": "-", "conflict": "!"}
_STATUS_COLOUR = {"add": "$success", "mod": "$warning", "del": "$error", "conflict": "$warning"}


def chip(text: str, colour: str = "$text-muted") -> str:
    """A small inline 'chip' rendered with a boosted background."""
    return f"[{colour} on $boost] {escape(text)} [/]"


def op_chip(op: str) -> str:
    return chip(op, _OP_COLOUR.get(op, "$text-muted"))


def risk_chip(risk: str) -> str:
    return chip(risk, _RISK_COLOUR.get(risk, "$text-muted"))


def op_colour(op: str) -> str:
    return _OP_COLOUR.get(op, "$text-muted")


def risk_colour(risk: str) -> str:
    return _RISK_COLOUR.get(risk, "$text-muted")


def status_glyph(status: str) -> str:
    if not status:
        return " "
    colour = _STATUS_COLOUR.get(status, "$text-muted")
    return f"[{colour}]{_STATUS_GLYPH.get(status, '·')}[/]"


# --------------------------------------------------------------------------- #
# Reusable widgets
# --------------------------------------------------------------------------- #


class SectionHeader(Static):
    """The per-view title row: bold heading + breadcrumb."""

    DEFAULT_CSS = """
    SectionHeader {
        height: auto;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $surface-lighten-1;
    }
    """

    def __init__(self, title: str, crumb: str = "") -> None:
        markup = f"[$primary bold]{escape(title)}[/]"
        if crumb:
            markup += f"   [$text-muted]{crumb}[/]"
        super().__init__(markup)


class Panel(Vertical):
    """A bordered, titled container — the workhorse layout box.

    The title is rendered in the border (via ``border_title``), so children
    passed through the usual ``with Panel(...): yield ...`` pattern are this
    widget's only composed content — no ``compose`` override to clash with.
    """

    DEFAULT_CSS = """
    Panel {
        height: auto;
        background: $surface;
        border: round $surface-lighten-1;
        border-title-color: $text-muted;
        border-title-style: bold;
        border-subtitle-color: $text-muted;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    """

    def __init__(self, title: str, *, subtitle: str = "", **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.border_title = title
        if subtitle:
            self.border_subtitle = subtitle
