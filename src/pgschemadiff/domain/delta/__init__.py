"""Delta package — shared foundation for the Phase 2 diff engine.

Public surface (the only names callers should import from this package)::

    from pgschemadiff.domain.delta import DeltaBase, DeltaOp, DeltaSet

Concrete delta subclasses (landing in tasks P2-DOM-01b..f) will also be
re-exported here once implemented, keeping the import surface clean.
"""

from __future__ import annotations

from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp, DeltaSet

__all__ = [
    "DeltaBase",
    "DeltaOp",
    "DeltaSet",
]
