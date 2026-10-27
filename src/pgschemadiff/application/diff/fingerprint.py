"""Canonical schema fingerprints."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pgschemadiff.domain.database import Database


def schema_fingerprint(database: Database) -> str:
    """Return a SHA-256 fingerprint for the schema snapshot, excluding database name."""
    snapshot = database.model_dump(mode="json")
    snapshot.pop("name")
    canonical = json.dumps(
        snapshot,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"sha256:{sha256(canonical).hexdigest()}"
