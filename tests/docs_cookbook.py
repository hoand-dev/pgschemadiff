"""Shared parser helpers for executable cookbook documentation."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import unquote

if TYPE_CHECKING:
    from pathlib import Path

_FENCE_START = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def parse_fenced_blocks(markdown: str) -> dict[str, list[str]]:
    """Return fenced code contents grouped by their complete info string."""
    blocks: dict[str, list[str]] = {}
    fence_char: str | None = None
    fence_length = 0
    info = ""
    content: list[str] = []

    for line in markdown.splitlines():
        if fence_char is None:
            match = _FENCE_START.match(line)
            if match is None:
                continue
            fence = match.group(1)
            fence_char = fence[0]
            fence_length = len(fence)
            info = match.group(2).strip()
            content = []
            continue

        closer = re.fullmatch(rf" {{0,3}}{re.escape(fence_char)}{{{fence_length},}}[ \t]*", line)
        if closer is not None:
            blocks.setdefault(info, []).append("\n".join(content))
            fence_char = None
            continue
        content.append(line)

    if fence_char is not None:
        raise ValueError("Unclosed fenced code block")
    return blocks


def validate_recipe(path: Path) -> dict[str, list[str]]:
    """Parse a recipe and require exactly one current, desired, and summary block."""
    blocks = parse_fenced_blocks(path.read_text(encoding="utf-8"))
    for info in ("sql current", "sql desired", "text summary"):
        if len(blocks.get(info, [])) != 1:
            raise ValueError(f"{path} must contain exactly one {info} block")
    return blocks


def recipe_paths(cookbook_root: Path) -> list[Path]:
    """List recipe Markdown files, excluding the cookbook index."""
    return sorted(path for path in cookbook_root.rglob("*.md") if path.name.lower() != "readme.md")


def find_broken_links(guide_root: Path) -> list[str]:
    """Return relative Markdown links in the guide that do not resolve to files."""
    broken: list[str] = []
    for source in sorted(guide_root.rglob("*.md")):
        markdown = source.read_text(encoding="utf-8")
        for match in _LINK.finditer(markdown):
            target = match.group(1).strip()
            if target.startswith("<") and ">" in target:
                target = target[1 : target.index(">")]
            else:
                target = target.split(maxsplit=1)[0]
            if target.lower().startswith(("http://", "https://")):
                continue

            relative_path = target.partition("#")[0]
            if not relative_path:
                continue
            resolved = (source.parent / unquote(relative_path)).resolve()
            if not resolved.is_file():
                broken.append(f"{source.relative_to(guide_root).as_posix()}: {target}")
    return broken
