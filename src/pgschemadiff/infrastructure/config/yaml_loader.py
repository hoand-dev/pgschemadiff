"""Load profiles from YAML file."""

from __future__ import annotations

from pathlib import Path

import yaml

from pgschemadiff.domain.models import Profile


class ProfileLoader:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path

    def load(self) -> list[Profile]:
        if not self.config_path.exists():
            return []
        with self.config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data or "profiles" not in data:
            return []
        return [Profile.model_validate(p) for p in data["profiles"]]

    def save(self, profiles: list[Profile]) -> None:
        payload = {"profiles": [p.model_dump() for p in profiles]}
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)
