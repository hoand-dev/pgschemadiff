"""Entry point: `python -m pgschemadiff`."""

from __future__ import annotations

import argparse
from pathlib import Path

from pgschemadiff.presentation.composition import create_tui_dependencies
from pgschemadiff.presentation.tui import PgsdApp


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
    dependencies = create_tui_dependencies(args.config)
    PgsdApp(dependencies=dependencies).run()


if __name__ == "__main__":
    main()
