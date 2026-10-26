"""Keep demo fixtures out of live TUI modules."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


@pytest.mark.unit
def test_only_mock_module_imports_tui_mock() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    tui_root = repository_root / "src" / "pgschemadiff" / "presentation" / "tui"
    violations: list[str] = []

    for source_path in tui_root.rglob("*.py"):
        if source_path.name == "_mock.py":
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                alias.name == "_mock" or alias.name.endswith("._mock") for alias in node.names
            ):
                violations.append(str(source_path.relative_to(tui_root)))
                break
            if isinstance(node, ast.ImportFrom):
                imports_mock_module = node.module is not None and (
                    node.module == "_mock" or node.module.endswith("._mock")
                )
                imports_mock_name = any(alias.name == "_mock" for alias in node.names)
                if imports_mock_module or imports_mock_name:
                    violations.append(str(source_path.relative_to(tui_root)))
                    break

    assert not violations, f"live TUI modules import _mock: {', '.join(violations)}"
