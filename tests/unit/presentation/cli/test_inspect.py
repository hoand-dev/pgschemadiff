from __future__ import annotations

import psycopg
import pytest
from typer.testing import CliRunner

import pgschemadiff.presentation.cli.commands.inspect as inspect_command
from pgschemadiff.presentation.cli.main import app
from pgschemadiff.shared.errors import InspectionError


class _FakePool:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure

    async def __aenter__(self) -> _FakePool:
        if self.failure is not None:
            raise self.failure
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        return None


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            psycopg.OperationalError("private connection detail"),
            "Lỗi: Không kết nối được cơ sở dữ liệu.",
        ),
        (
            InspectionError("private inspection detail"),
            "Lỗi: Không đọc được schema.",
        ),
    ],
)
def test_inspect_errors_use_vietnamese_and_redact_details(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected: str,
) -> None:
    monkeypatch.setattr(
        inspect_command,
        "Pool",
        lambda *_args, **_kwargs: _FakePool(failure=failure),
    )

    result = CliRunner().invoke(
        app,
        ["inspect", "postgresql://source/db"],
        env={"PGSD_LANG": "vi"},
    )

    assert result.exit_code == 1
    assert result.stderr == expected + "\n"
    assert "private" not in result.stderr


def test_inspect_json_stays_unchanged_in_vietnamese(monkeypatch: pytest.MonkeyPatch) -> None:
    async def inspect_schema(_inspector: object) -> str:
        return '{"schemas": []}'

    monkeypatch.setattr(inspect_command, "Pool", lambda *_args, **_kwargs: _FakePool())
    monkeypatch.setattr(inspect_command, "PgCatalogInspector", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(inspect_command, "inspect_schema", inspect_schema)

    result = CliRunner().invoke(
        app,
        ["inspect", "postgresql://source/db"],
        env={"PGSD_LANG": "vi"},
    )

    assert result.exit_code == 0
    assert result.stdout == '{"schemas": []}\n'
    assert result.stderr == ""
