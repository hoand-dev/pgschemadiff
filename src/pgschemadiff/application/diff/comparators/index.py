"""Index comparator (task P2-DIFF-04).

Implements :class:`IndexComparator`, the :class:`~pgschemadiff.application.diff.engine.Comparator`
for :attr:`~pgschemadiff.domain.identity.ObjectKind.INDEX` objects.

Structural vs. non-structural fields
-------------------------------------
PostgreSQL indexes are essentially immutable once created.  The only in-place
changes that Postgres supports are identity-only operations (RENAME, SET
TABLESPACE, SET storage_parameters — all out of MVP-A scope).  Therefore, any
difference in a *structural* attribute requires a full ``DROP INDEX`` +
``CREATE INDEX`` cycle, expressed as a :class:`~pgschemadiff.domain.delta.ReplaceIndex`
delta.

The structural fields compared by this comparator are:

- ``method`` — access method (btree / hash / gist / gin / brin / spgist)
- ``key_columns`` — ordered key-column tuple (name, expression, opclass,
  sort order, nulls order)
- ``include_columns`` — ``INCLUDE`` column list (covering index)
- ``unique`` — uniqueness flag
- ``predicate`` — ``WHERE`` predicate for partial indexes

The ``comment`` field is *non-structural*: a comment-only difference does not
require a rebuild.  However, there is no ``AlterIndexComment`` delta type in
MVP-A.  Therefore a **comment-only difference is silently ignored** (returns
an empty tuple).  This is a deliberate deferral; a future
``CommentOnIndex`` delta type (P3-SQL-04 or later) can be added without
changing this comparator's structural logic.

Typing note
-----------
:meth:`IndexComparator.compare` narrows its signature to ``Index | None``
while the :class:`~pgschemadiff.application.diff.engine.Comparator` Protocol
declares ``object | None``.  This is a covariant narrowing that is safe at
runtime because the :class:`~pgschemadiff.application.diff.engine.DiffEngine`
always passes ``Index`` objects (or ``None``) when dispatching for
``ObjectKind.INDEX``.  mypy strict mode flags this as a ``[override]``
incompatibility; the ``# type: ignore[override]`` annotation is applied per the
typing strategy documented in :mod:`pgschemadiff.application.diff.engine`.

Layer contract
--------------
Pure application layer: domain + stdlib only.  No IO, no async, no psycopg,
no infra/presentation imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.application.diff.engine import Comparator
from pgschemadiff.domain.delta.index import CreateIndex, DropIndex, ReplaceIndex
from pgschemadiff.domain.identity import ObjectKind

if TYPE_CHECKING:
    from pgschemadiff.domain.index import Index

# ---------------------------------------------------------------------------
# IndexComparator
# ---------------------------------------------------------------------------

# The structural fields that require a DROP + CREATE when they differ.
# ``comment`` is intentionally excluded: comment-only diffs are deferred.
_STRUCTURAL_FIELDS: tuple[str, ...] = (
    "method",
    "key_columns",
    "include_columns",
    "unique",
    "predicate",
)


def _structurally_equal(source: Index, target: Index) -> bool:
    """Return ``True`` iff *source* and *target* share identical structural attributes.

    Compares each field in :data:`_STRUCTURAL_FIELDS` explicitly, making the
    rule visible and independently testable.  The ``comment`` field is
    deliberately excluded — a comment-only difference does not trigger a
    replace (see module docstring for rationale).
    """
    return all(getattr(source, field) == getattr(target, field) for field in _STRUCTURAL_FIELDS)


class IndexComparator:
    """Comparator for :attr:`~pgschemadiff.domain.identity.ObjectKind.INDEX` objects.

    Registered with :class:`~pgschemadiff.application.diff.engine.DiffEngine` to
    handle index-level diffing.  Implements the
    :class:`~pgschemadiff.application.diff.engine.Comparator` Protocol structurally
    (duck-typed); verified at test time via ``isinstance(IndexComparator(), Comparator)``.

    Decision table
    --------------
    +--------------------+--------------------+-------------------------------+
    | source             | target             | emitted deltas                |
    +====================+====================+===============================+
    | ``None``           | :class:`Index`     | ``(CreateIndex(...),)``       |
    +--------------------+--------------------+-------------------------------+
    | :class:`Index`     | ``None``           | ``(DropIndex(...),)``         |
    +--------------------+--------------------+-------------------------------+
    | :class:`Index`     | :class:`Index`     | ``(ReplaceIndex(...),)`` if   |
    |                    |                    | any structural field differs; |
    |                    |                    | ``()`` if identical or        |
    |                    |                    | comment-only diff             |
    +--------------------+--------------------+-------------------------------+
    | ``None``           | ``None``           | ``()`` (defensive; the engine |
    |                    |                    | never calls this branch)      |
    +--------------------+--------------------+-------------------------------+

    Comment-only differences
    ------------------------
    A change limited to the ``comment`` field is a non-structural diff that
    PostgreSQL handles with ``COMMENT ON INDEX …``.  No ``AlterIndexComment``
    delta exists in MVP-A, so comment-only diffs emit an empty tuple.  This is
    intentional and documented; add a ``CommentOnIndex`` delta in a later phase
    if needed.
    """

    kind: ObjectKind = ObjectKind.INDEX

    def compare(
        self,
        source: Index | None,
        target: Index | None,
    ) -> tuple[CreateIndex | DropIndex | ReplaceIndex, ...]:
        """Compare one source/target index pair and emit the appropriate deltas.

        Parameters
        ----------
        source:
            The index as it exists in the *current* (source) database, or
            ``None`` if the index does not exist there.
        target:
            The index as it exists in the *desired* (target) database, or
            ``None`` if the index should be dropped.

        Returns
        -------
        tuple
            Zero or one delta in a tuple.  Never returns more than one delta
            per call (replace covers both drop + create semantically).
        """
        # --- CREATE: exists only in target -----------------------------------
        if source is None and target is not None:
            return (CreateIndex(target=target.ref, index=target),)

        # --- DROP: exists only in source -------------------------------------
        if source is not None and target is None:
            return (DropIndex(target=source.ref, index=source),)

        # --- Defensive: both None (engine should never call this) ------------
        if source is None or target is None:
            return ()

        # --- Both present: compare structural fields -------------------------
        if _structurally_equal(source, target):
            # No structural change.  Comment-only differences are deferred
            # (no AlterIndexComment delta in MVP-A).
            return ()

        return (ReplaceIndex(target=target.ref, old_index=source, new_index=target),)


# Runtime check: ensure IndexComparator is a structural match for the Protocol.
# This is evaluated at import time; a test also verifies it explicitly.
assert isinstance(IndexComparator(), Comparator), (
    "IndexComparator must satisfy the Comparator Protocol"
)

__all__: list[str] = ["IndexComparator"]
