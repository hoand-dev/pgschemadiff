"""Load explicit rename annotations from YAML or TOML."""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

import yaml
from yaml.constructor import ConstructorError

from pgschemadiff.application.diff.renames import RenameAnnotations
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from pathlib import Path

    from yaml.nodes import MappingNode


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects ambiguous duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    """Construct a mapping while rejecting duplicate keys at every level."""
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key: object = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def load_renames(path: Path) -> RenameAnnotations:
    """Parse a YAML or TOML rename annotation file."""
    suffix = path.suffix.lower()
    if suffix not in {".yaml", ".yml", ".toml"}:
        raise DiffError(f"Unsupported rename file extension: {suffix or '<none>'}")

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DiffError(f"Unable to read rename annotations from {path}: {exc}") from exc

    try:
        document = (
            tomllib.loads(text)
            if suffix == ".toml"
            else yaml.load(text, Loader=_UniqueKeySafeLoader)
        )
    except (tomllib.TOMLDecodeError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise DiffError(f"Unable to parse rename annotations from {path}: {exc}") from exc

    try:
        return RenameAnnotations.from_document(document)
    except DiffError as exc:
        raise DiffError(f"Invalid rename annotations in {path}: {exc}") from exc


__all__ = ["load_renames"]
