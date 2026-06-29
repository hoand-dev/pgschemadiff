"""Application diff package — public surface for the diff engine.

Exports:
    :class:`Comparator` — per-kind comparison Protocol (ADR-0006).
    :class:`DiffEngine` — central visitor dispatcher.
    :func:`topological_sort` — Kahn topological sort (task P2-DIFF-08).
"""

from __future__ import annotations

from pgschemadiff.application.diff.engine import Comparator, DiffEngine
from pgschemadiff.application.diff.topo_sort import topological_sort

__all__ = [
    "Comparator",
    "DiffEngine",
    "topological_sort",
]
