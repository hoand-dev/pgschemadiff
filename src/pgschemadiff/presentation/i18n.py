"""Language selection and message lookup for human-facing CLI output."""

from __future__ import annotations

import os
from typing import Literal

from pgschemadiff.presentation.i18n_catalog import EN, VI

Language = Literal["en", "vi"]


def current_language() -> Language:
    """Resolve the CLI language from PGSD_LANG or the active locale."""
    configured = os.environ.get("PGSD_LANG")
    if configured is not None:
        return "vi" if configured.lower() == "vi" else "en"

    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        locale = os.environ.get(name, "")
        if locale:
            return "vi" if locale.lower().startswith("vi") else "en"
    return "en"


def t(key: str, /, **params: object) -> str:
    """Format a catalog message, falling back to English when untranslated."""
    language = current_language()
    template = VI.get(key, EN[key]) if language == "vi" else EN[key]
    return template.format(**params)
