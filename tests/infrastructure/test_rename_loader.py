"""Tests for loading rename annotation files."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pgschemadiff.application.diff.renames import RenameAnnotations
from pgschemadiff.infrastructure.config.rename_loader import load_renames
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from pathlib import Path


def test_yaml_and_toml_load_to_same_annotations(tmp_path: Path) -> None:
    yaml_path = tmp_path / "renames.yml"
    yaml_path.write_text(
        "renames:\n"
        "  - kind: table\n"
        "    from: public.user_account\n"
        "    to: public.users\n"
        "  - kind: column\n"
        "    from: public.users.email_addr\n"
        "    to: public.users.email\n",
        encoding="utf-8",
    )
    toml_path = tmp_path / "renames.toml"
    toml_path.write_text(
        '[[renames]]\nkind = "table"\nfrom = "public.user_account"\n'
        'to = "public.users"\n\n'
        '[[renames]]\nkind = "column"\nfrom = "public.users.email_addr"\n'
        'to = "public.users.email"\n',
        encoding="utf-8",
    )

    assert load_renames(yaml_path) == load_renames(toml_path)
    assert isinstance(load_renames(yaml_path), RenameAnnotations)


@pytest.mark.parametrize("suffix", [".json", ".cfg", ""])
def test_reject_unsupported_file_extension(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"renames{suffix}"
    path.write_text("renames: []", encoding="utf-8")

    with pytest.raises(DiffError, match="extension"):
        load_renames(path)


def test_missing_file_raises_diff_error(tmp_path: Path) -> None:
    with pytest.raises(DiffError, match="read"):
        load_renames(tmp_path / "missing.yml")


def test_duplicate_yaml_keys_raise_diff_error(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.yml"
    path.write_text(
        "renames:\n"
        "  - kind: table\n"
        "    from: public.old\n"
        "    from: public.other\n"
        "    to: public.new\n",
        encoding="utf-8",
    )

    with pytest.raises(DiffError, match="parse"):
        load_renames(path)


@pytest.mark.parametrize(
    ("name", "contents"),
    [("broken.yml", "renames: ["), ("broken.toml", "[[renames]\nkind = ")],
)
def test_malformed_file_raises_diff_error(tmp_path: Path, name: str, contents: str) -> None:
    path = tmp_path / name
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(DiffError, match="parse"):
        load_renames(path)
