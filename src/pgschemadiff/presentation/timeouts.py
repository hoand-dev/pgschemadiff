"""Timeout parsing shared by presentation entry points."""

from __future__ import annotations

import re

_TIMEOUT_PATTERN = re.compile(r"(?:0|[0-9]+(?:ms|s|min))\Z")
_MAX_TIMEOUT_MS = 86_400_000  # Matches the executor's accepted range.


def parse_timeout(value: str, option: str) -> int:
    """Convert a non-negative CLI timeout to milliseconds."""
    if _TIMEOUT_PATTERN.fullmatch(value) is None:
        raise ValueError(f"Error: Invalid value for {option}.")
    if value == "0":
        return 0

    for suffix, multiplier in (("min", 60_000), ("ms", 1), ("s", 1_000)):
        if value.endswith(suffix):
            milliseconds = int(value[: -len(suffix)]) * multiplier
            if milliseconds > _MAX_TIMEOUT_MS:
                raise ValueError(f"Error: {option} must not exceed 24 hours.")
            return milliseconds
    raise ValueError(f"Error: Invalid value for {option}.")
