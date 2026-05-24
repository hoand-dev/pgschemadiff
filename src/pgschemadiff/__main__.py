"""Entry point: `python -m pgschemadiff`."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from pgschemadiff.presentation.app import PgSchemaDiffApp


def _default_config_path() -> Path:
    """Tìm config theo thứ tự ưu tiên:
    1. $PGSCHEMADIFF_CONFIG
    2. ./config/profiles.yaml (dev)
    3. $XDG_CONFIG_HOME/pgschemadiff/profiles.yaml
    4. ~/.config/pgschemadiff/profiles.yaml
    """
    env = os.environ.get("PGSCHEMADIFF_CONFIG")
    if env:
        return Path(env).expanduser()

    local = Path.cwd() / "config" / "profiles.yaml"
    if local.exists():
        return local

    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "pgschemadiff" / "profiles.yaml"


def main() -> None:
    parser = argparse.ArgumentParser(prog="pgschemadiff")
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=None,
        help="Path to profiles.yaml (default: auto-detect)",
    )
    args = parser.parse_args()
    config_path = args.config or _default_config_path()

    app = PgSchemaDiffApp(config_path=config_path)
    app.run()


if __name__ == "__main__":
    main()
