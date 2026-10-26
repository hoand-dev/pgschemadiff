"""Format and link checks for the user guide and cookbook."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from tests import docs_cookbook

if TYPE_CHECKING:
    from collections.abc import Callable

ROOT = Path(__file__).resolve().parents[3]
GUIDE_ROOT = ROOT / "docs" / "guide"


def _helper(name: str) -> object | None:
    return getattr(docs_cookbook, name, None)


def test_parse_fenced_blocks_groups_by_info_string() -> None:
    parser = _helper("parse_fenced_blocks")
    assert callable(parser), "tests.docs_cookbook.parse_fenced_blocks is missing"
    parse = cast("Callable[[str], dict[str, list[str]]]", parser)

    blocks = parse(
        """```sql current
CREATE TABLE cookbook.users (id integer);
```
```sql up
ALTER TABLE cookbook.users ADD COLUMN email text;
```
```sql up
CREATE INDEX users_email_idx ON cookbook.users (email);
```
"""
    )

    assert blocks == {
        "sql current": ["CREATE TABLE cookbook.users (id integer);"],
        "sql up": [
            "ALTER TABLE cookbook.users ADD COLUMN email text;",
            "CREATE INDEX users_email_idx ON cookbook.users (email);",
        ],
    }


def test_validate_recipe_requires_current_sql(tmp_path: Path) -> None:
    validator = _helper("validate_recipe")
    assert callable(validator), "tests.docs_cookbook.validate_recipe is missing"
    validate = cast("Callable[[Path], dict[str, list[str]]]", validator)
    recipe = tmp_path / "missing-current.md"
    recipe.write_text(
        """```sql desired
CREATE TABLE cookbook.users (id integer);
```
```text summary
No changes.
```
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="sql current"):
        validate(recipe)


def test_guide_links_resolve_and_http_links_are_ignored(tmp_path: Path) -> None:
    checker = _helper("find_broken_links")
    assert callable(checker), "tests.docs_cookbook.find_broken_links is missing"
    find_broken = cast("Callable[[Path], list[str]]", checker)
    guide = tmp_path / "guide"
    guide.mkdir()
    (guide / "page.md").write_text("# Page\n", encoding="utf-8")
    (guide / "README.md").write_text(
        "[page](page.md) [anchor](#page) [external](https://example.com) [missing](missing.md)\n",
        encoding="utf-8",
    )

    assert find_broken(guide) == ["README.md: missing.md"]


def test_every_recipe_has_required_blocks() -> None:
    list_recipes = _helper("recipe_paths")
    validate_recipe = _helper("validate_recipe")
    assert callable(list_recipes), "tests.docs_cookbook.recipe_paths is missing"
    assert callable(validate_recipe), "tests.docs_cookbook.validate_recipe is missing"
    paths = cast("Callable[[Path], list[Path]]", list_recipes)(GUIDE_ROOT / "cookbook")
    validate = cast("Callable[[Path], dict[str, list[str]]]", validate_recipe)

    assert len(paths) == 9
    for path in paths:
        blocks = validate(path)
        assert len(blocks.get("sql current", [])) == 1, path
        assert len(blocks.get("sql desired", [])) == 1, path
        assert len(blocks.get("text summary", [])) == 1, path


def test_all_guide_links_resolve() -> None:
    checker = _helper("find_broken_links")
    assert callable(checker), "tests.docs_cookbook.find_broken_links is missing"
    find_broken = cast("Callable[[Path], list[str]]", checker)

    assert find_broken(GUIDE_ROOT) == []
