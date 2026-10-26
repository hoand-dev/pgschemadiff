from __future__ import annotations

from importlib import import_module, util
from io import StringIO
from typing import TYPE_CHECKING, Any

import pytest
import typer
from rich.console import Console

from pgschemadiff.application.sql_emit.risk import RiskLevel

if TYPE_CHECKING:
    from types import ModuleType


def _output() -> ModuleType:
    spec = util.find_spec("pgschemadiff.presentation.cli.output")
    assert spec is not None
    return import_module("pgschemadiff.presentation.cli.output")


def _capture_console(
    monkeypatch: pytest.MonkeyPatch,
    output: ModuleType,
    *,
    terminal: bool,
) -> StringIO:
    stream = StringIO()

    def create_console(**kwargs: Any) -> Console:
        return Console(
            file=stream,
            force_terminal=terminal,
            color_system="standard",
            **kwargs,
        )

    monkeypatch.setattr(output, "Console", create_console)
    return stream


def test_stderr_console_disables_markup_and_highlighting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = _output()
    seen: dict[str, object] = {}
    console = object()

    def create_console(**kwargs: object) -> object:
        seen.update(kwargs)
        return console

    monkeypatch.setattr(output, "Console", create_console)

    assert output.stderr_console() is console
    assert seen == {
        "stderr": True,
        "markup": False,
        "highlight": False,
        "emoji": False,
        "soft_wrap": True,
    }


def test_error_prints_message_to_stderr_and_exits_with_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = _output()
    stream = _capture_console(monkeypatch, output, terminal=False)

    with pytest.raises(typer.Exit) as raised:
        output.error("Error: invalid input.", 2)

    assert raised.value.exit_code == 2
    assert stream.getvalue() == "Error: invalid input.\n"


def test_warn_colors_only_when_stderr_is_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    output = _output()
    plain = _capture_console(monkeypatch, output, terminal=False)

    output.warn("careful")

    assert plain.getvalue() == "careful\n"

    terminal = _capture_console(monkeypatch, output, terminal=True)
    output.warn("careful")

    assert "careful" in terminal.getvalue()
    assert "\x1b[" in terminal.getvalue()


def test_progress_prints_only_when_stderr_is_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = _output()
    non_terminal = _capture_console(monkeypatch, output, terminal=False)

    output.progress(1, 3, "Inspecting source")

    assert non_terminal.getvalue() == ""

    terminal = _capture_console(monkeypatch, output, terminal=True)
    output.progress(1, 3, "Inspecting source")

    assert "[1/3] Inspecting source" in terminal.getvalue()
    assert "\x1b[" in terminal.getvalue()


@pytest.mark.parametrize(
    ("level", "style"),
    [
        (RiskLevel.SAFE, "green"),
        (RiskLevel.WARNING, "yellow"),
        (RiskLevel.DANGEROUS, "magenta"),
        (RiskLevel.DESTRUCTIVE, "red"),
        (RiskLevel.BLOCKED, "bold red"),
    ],
)
def test_risk_text_uses_specified_style(
    monkeypatch: pytest.MonkeyPatch,
    level: RiskLevel,
    style: str,
) -> None:
    output = _output()
    _capture_console(monkeypatch, output, terminal=False)

    text = output.risk_text(level)

    assert text.plain == level.value
    assert str(text.style) == style
    assert output.risk_text(None).plain == "none"


def test_no_color_keeps_markup_like_error_text_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    output = _output()
    stream = _capture_console(monkeypatch, output, terminal=True)

    with pytest.raises(typer.Exit):
        output.error("Error: object [red]x[/] is invalid.", 2)

    assert stream.getvalue() == "Error: object [red]x[/] is invalid.\n"


def test_error_uses_ansi_color_for_terminal_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    output = _output()
    stream = _capture_console(monkeypatch, output, terminal=True)

    with pytest.raises(typer.Exit):
        output.error("Error: failed.", 1)

    assert "Error: failed." in stream.getvalue()
    assert "\x1b[" in stream.getvalue()
