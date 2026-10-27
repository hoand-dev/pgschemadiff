from __future__ import annotations

import ast
from pathlib import Path
from string import Formatter

import pytest

from pgschemadiff.presentation import i18n, i18n_catalog

_ALLOWED_UNTRANSLATED_OUTPUTS: dict[tuple[str, str], str] = {
    # `diff --format summary` is stdout data; its English bytes are stable.
    ("commands/diff.py", "_print_summary"): ("'No schema changes.'"),
    # Dry-run unit records are explicitly English and remain byte-stable.
    ("commands/apply.py", "_print_dry_run"): ("f'unit "),
    # Apply event lines are log-like records, including key=value fields.
    ("commands/apply.py", "_print_event"): ("line"),
    # Version output contains the tool identifier and version, not prose.
    ("main.py", "_version_callback"): ("f'pgschemadiff "),
}


def _clear_language_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("PGSD_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    ("language", "expected"),
    [("VI", "vi"), ("EN", "en"), ("fr", "en"), ("", "en")],
)
def test_pgsd_lang_overrides_locale_and_invalid_value_defaults_to_english(
    monkeypatch: pytest.MonkeyPatch,
    language: str,
    expected: str,
) -> None:
    _clear_language_environment(monkeypatch)
    monkeypatch.setenv("PGSD_LANG", language)
    monkeypatch.setenv("LC_ALL", "vi_VN.UTF-8" if expected == "en" else "en_US.UTF-8")

    assert i18n.current_language() == expected


@pytest.mark.parametrize(
    ("locales", "expected"),
    [
        (("vi_VN.UTF-8", "en_US.UTF-8", "en_US.UTF-8"), "vi"),
        (("", "vi_VN.UTF-8", "en_US.UTF-8"), "vi"),
        (("", "", "vi_VN.UTF-8"), "vi"),
        (("fr_FR.UTF-8", "vi_VN.UTF-8", "vi_VN.UTF-8"), "en"),
        (("", "", ""), "en"),
    ],
)
def test_locale_selection_uses_first_nonempty_locale(
    monkeypatch: pytest.MonkeyPatch,
    locales: tuple[str, str, str],
    expected: str,
) -> None:
    _clear_language_environment(monkeypatch)
    for name, value in zip(("LC_ALL", "LC_MESSAGES", "LANG"), locales, strict=True):
        monkeypatch.setenv(name, value)

    assert i18n.current_language() == expected


def test_translation_falls_back_to_english_when_vietnamese_key_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_language_environment(monkeypatch)
    monkeypatch.setenv("PGSD_LANG", "vi")
    monkeypatch.setitem(i18n_catalog.EN, "test.fallback", "English {value}")
    monkeypatch.delitem(i18n_catalog.VI, "test.fallback", raising=False)

    assert i18n.t("test.fallback", value="text") == "English text"


def test_translation_formats_named_placeholders_in_selected_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_language_environment(monkeypatch)
    monkeypatch.setenv("PGSD_LANG", "vi")
    monkeypatch.setitem(i18n_catalog.EN, "test.format", "English {value}")
    monkeypatch.setitem(i18n_catalog.VI, "test.format", "Tiếng Việt {value}")

    assert i18n.t("test.format", value="text") == "Tiếng Việt text"


@pytest.mark.parametrize("language", ["en", "vi"])
def test_translation_raises_for_unknown_key(
    monkeypatch: pytest.MonkeyPatch,
    language: str,
) -> None:
    _clear_language_environment(monkeypatch)
    monkeypatch.setenv("PGSD_LANG", language)

    with pytest.raises(KeyError, match=r"missing\.key"):
        i18n.t("missing.key")


def test_catalogs_have_matching_keys_and_named_placeholders() -> None:
    assert i18n_catalog.EN.keys() == i18n_catalog.VI.keys()
    formatter = Formatter()
    for key in i18n_catalog.EN:
        english_fields = {
            field
            for _literal, field, _format_spec, _conversion in formatter.parse(i18n_catalog.EN[key])
            if field is not None
        }
        vietnamese_fields = {
            field
            for _literal, field, _format_spec, _conversion in formatter.parse(i18n_catalog.VI[key])
            if field is not None
        }
        assert english_fields == vietnamese_fields, key
        assert all(field.isidentifier() for field in english_fields), key


def test_cli_human_message_literals_are_catalogued_or_explicitly_allowlisted() -> None:
    repository = Path(__file__).resolve().parents[3]
    cli_root = repository / "src" / "pgschemadiff" / "presentation" / "cli"
    untranslated: list[str] = []

    class MessageCallVisitor(ast.NodeVisitor):
        def __init__(self, relative_path: str) -> None:
            self.relative_path = relative_path
            self.function_name = "<module>"

        def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            previous = self.function_name
            self.function_name = node.name
            self.generic_visit(node)
            self.function_name = previous

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_function(node)

        def visit_Call(self, node: ast.Call) -> None:
            name = _call_name(node.func)
            if name not in {
                "output.error",
                "output.warn",
                "output.progress",
                "_exit",
                "typer.confirm",
                "typer.echo",
            }:
                self.generic_visit(node)
                return

            argument_index = 2 if name == "output.progress" else 0
            if len(node.args) > argument_index:
                message = node.args[argument_index]
                if not _is_translation(message) and _contains_string_literal(message):
                    rendered = ast.unparse(message)
                    allowed = _ALLOWED_UNTRANSLATED_OUTPUTS.get(
                        (self.relative_path, self.function_name)
                    )
                    if allowed is None or not rendered.startswith(allowed):
                        untranslated.append(f"{self.relative_path}:{node.lineno}: {rendered}")
            self.generic_visit(node)

    for source_path in sorted(cli_root.rglob("*.py")):
        if source_path.name == "i18n_catalog.py":
            continue
        relative_path = source_path.relative_to(cli_root).as_posix()
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=relative_path)
        MessageCallVisitor(relative_path).visit(tree)

    assert untranslated == []


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_call_name(node.value)}.{node.attr}"
    return ""


def _is_translation(node: ast.expr) -> bool:
    return isinstance(node, ast.Call) and _call_name(node.func) == "t"


def _contains_string_literal(node: ast.expr) -> bool:
    return any(
        isinstance(child, ast.Constant) and isinstance(child.value, str) for child in ast.walk(node)
    )
