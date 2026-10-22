"""Diff engine visitor dispatcher (task P2-DIFF-01).

This module delivers the **dispatch framework** for the Phase 2 diff engine.
Per ADR-0006, each :class:`~pgschemadiff.domain.identity.ObjectKind` has a
dedicated :class:`Comparator` (a :class:`typing.Protocol`).  The central
:class:`DiffEngine` enumerates objects from a pair of
:class:`~pgschemadiff.domain.database.Database` snapshots, pairs them by
stable identity, and dispatches each pair to the registered comparator,
collecting all emitted :class:`~pgschemadiff.domain.delta.DeltaBase` instances
into a single :class:`~pgschemadiff.domain.delta.DeltaSet`.

Design notes
------------
Open/Closed principle
    Adding a new object kind requires only registering one more ``Comparator``
    instance — zero edits to ``DiffEngine`` itself (ADR-0006 "Positive").

Determinism
    Objects within each kind are sorted by their :class:`QualifiedName`
    ``(namespace, name)`` tuple before dispatch, so the resulting
    :class:`DeltaSet` is built in a stable, reproducible order regardless of
    the order schemas/tables/indexes happen to be stored in a :class:`Database`.

    This pre-sort is intentionally lightweight — it is **not** a dependency-
    aware topological sort.  Downstream topo-ordering is a separate step
    handled by :mod:`pgschemadiff.application.diff.topo_sort` (task P2-DIFF-08)
    and wired together in the ``pgsd diff`` CLI command (task P2-CLI-01).

Typing strategy
    The payload passed to ``Comparator.compare`` varies per kind (a
    ``Table`` comparator receives ``Table | None``; a ``Schema`` comparator
    receives ``Schema | None``).  Rather than duplicating the Protocol for
    every combination, ``Comparator`` is declared with ``object | None``
    payload so that a single Protocol covers all comparators.  Concrete
    implementations declare a narrower type in their own ``compare`` signature
    — this is safe because callers (the engine) always pass the exact domain
    object type that matches the ``kind`` the comparator declared.

    If mypy strict mode requires it, individual comparator modules may declare
    ``# type: ignore[override]`` on the narrower ``compare`` signature when
    subtyping the Protocol, or use a ``Comparator[T]`` generic variant.  See
    the module-level ``Comparator`` docstring for discussion.

Layer contract
    Pure application layer: no IO, no async, no psycopg, no infra/presentation
    imports.  Depends only on :mod:`pgschemadiff.domain` and stdlib.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

from pgschemadiff.domain.delta import DeltaBase, DeltaSet
from pgschemadiff.domain.identity import ObjectKind, QualifiedName
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pgschemadiff.application.diff.ignore import IgnoreRules
    from pgschemadiff.application.diff.renames import RenameAnnotations
    from pgschemadiff.domain.database import Database
    from pgschemadiff.domain.index import Index


# ---------------------------------------------------------------------------
# Comparator Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Comparator(Protocol):
    """Per-kind comparison contract.

    Each concrete implementation handles exactly **one**
    :class:`~pgschemadiff.domain.identity.ObjectKind` and must be registered
    with :class:`DiffEngine` before it can be used.

    Attributes
    ----------
    kind:
        The :class:`~pgschemadiff.domain.identity.ObjectKind` this comparator
        handles.  Used by :class:`DiffEngine` to index the registry and to
        dispatch paired objects.

    ``compare`` semantics
    ----------------------
    ``source`` is the object as it exists in the *source* (current) database;
    ``target`` is the object as it exists in the *target* (desired) database.

    * Both present → potential ALTER / RENAME / REPLACE (comparator decides).
    * ``source is None`` → object exists only in the target → emit a CREATE
      delta (or equivalent).
    * ``target is None`` → object exists only in the source → emit a DROP
      delta (or equivalent).
    * The comparator is free to return an empty tuple when the two objects
      are semantically identical.

    Return type
    -----------
    A ``tuple[DeltaBase, ...]`` (or any ``Iterable[DeltaBase]``) of concrete
    delta subclasses.  The engine treats an empty return as "no change".

    Typing note
    -----------
    The payload type is declared ``object | None`` so that a single Protocol
    definition covers all concrete comparators.  A comparator for ``TABLE``
    will narrow its own ``compare`` signature to ``Table | None`` — this is a
    covariant narrowing that mypy accepts when the Protocol is used
    structurally (duck-typed).  The engine is responsible for passing the
    correct domain object for the declared ``kind``; type safety at the call
    site is enforced by :meth:`DiffEngine._fetch_objects` which pairs objects
    keyed by ``ObjectKind``.
    """

    kind: ObjectKind

    def compare(
        self,
        source: object | None,
        target: object | None,
    ) -> Iterable[DeltaBase]:
        """Compare one (source, target) pair and return the emitted deltas."""
        ...


@runtime_checkable
class RenameAwareComparator(Protocol):
    """Optional comparator capability for explicit rename context."""

    def compare_with_renames(
        self,
        source: object | None,
        target: object | None,
        renames: RenameAnnotations,
    ) -> Iterable[DeltaBase]:
        """Compare a pair while honoring explicit rename annotations."""
        ...


# ---------------------------------------------------------------------------
# Internal helpers — object enumeration per kind
# ---------------------------------------------------------------------------


def _qname_sort_key(qname: QualifiedName) -> tuple[str, str]:
    """Return a stable lexicographic sort key for a :class:`QualifiedName`."""
    return (qname.namespace, qname.name)


def _fetch_objects_for_kind(
    db: Database,
    kind: ObjectKind,
) -> dict[QualifiedName, object]:
    """Return a mapping of :class:`QualifiedName` → domain object for *kind*.

    Only the object kinds that the MVP-A diff engine knows about are
    enumerated.  Unknown kinds return an empty dict so that newly-registered
    comparators for not-yet-introspected kinds produce an empty diff rather
    than an error.

    This function is intentionally a pure helper — it performs no IO and
    carries no per-kind comparison semantics.
    """
    if kind is ObjectKind.SCHEMA:
        return {s.ref.qname: s for s in db.schemas}

    if kind is ObjectKind.EXTENSION:
        return {e.ref.qname: e for e in db.extensions}

    if kind is ObjectKind.TABLE:
        return {t.ref.qname: t for t in db.all_tables()}

    if kind is ObjectKind.INDEX:
        return {i.ref.qname: i for i in db.all_indexes()}

    # Other kinds (VIEW, FUNCTION, etc.) are not yet introspected.
    # Return empty — the engine will generate no pairs, so the comparator
    # will never be called and will emit no deltas.  This is the correct
    # behaviour during incremental MVP-A roll-out; add fetchers here as each
    # kind gains introspection support.
    return {}


# ---------------------------------------------------------------------------
# DiffEngine
# ---------------------------------------------------------------------------


class DiffEngine:
    """Central dispatcher that pairs objects across two databases and routes
    each pair to the matching :class:`Comparator`.

    Construction
    ------------
    Pass an iterable of :class:`Comparator` instances — one per
    :class:`~pgschemadiff.domain.identity.ObjectKind`::

        from pgschemadiff.application.diff.engine import DiffEngine

        engine = DiffEngine(comparators=[table_cmp, schema_cmp, extension_cmp])

    Registering two comparators for the same ``kind`` raises :exc:`DiffError`
    at construction time so misconfigurations are caught eagerly.

    Usage
    -----
    ::

        delta_set = engine.diff(source_db, target_db)

    The returned :class:`~pgschemadiff.domain.delta.DeltaSet` collects every
    delta emitted by every registered comparator in a deterministic,
    reproducible order (sorted by qualified name within each kind, kinds
    iterated in the order they were registered).

    Unknown kind
    ------------
    If a comparator is registered for a kind that has no object fetcher
    (e.g. a future ``VIEW`` comparator before the inspector supports views),
    the engine will call ``compare(None, None)`` zero times — the comparator
    simply never fires.  This is the documented "no pairs → no deltas"
    behaviour and is NOT an error.  An error IS raised if you call
    :meth:`diff` and there is NO registered comparator for a kind that
    *does* have objects — but currently we only raise on duplicate-kind
    registration, trusting callers to register exactly the kinds they care
    about.
    """

    def __init__(self, comparators: Iterable[Comparator]) -> None:
        """Construct the engine with the given comparator registry.

        Parameters
        ----------
        comparators:
            An iterable of :class:`Comparator` instances.  Each must declare a
            unique ``kind``.  Duplicates raise :exc:`DiffError` immediately.

        Raises
        ------
        pgschemadiff.shared.errors.DiffError
            If two comparators declare the same
            :class:`~pgschemadiff.domain.identity.ObjectKind`.
        """
        self._registry: dict[ObjectKind, Comparator] = {}
        for cmp in comparators:
            if cmp.kind in self._registry:
                raise DiffError(
                    f"Duplicate comparator registration for ObjectKind {cmp.kind!r}.  "
                    f"Each kind may have at most one comparator."
                )
            self._registry[cmp.kind] = cmp

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def diff(
        self,
        source: Database,
        target: Database,
        *,
        renames: RenameAnnotations | None = None,
        ignore: IgnoreRules | None = None,
    ) -> DeltaSet:
        """Compare two database snapshots and return the collected deltas.

        For each registered :class:`Comparator` (in registration order):

        1. Fetch all objects of that kind from both *source* and *target*.
        2. Build the union of all qualified names across both sides.
        3. Sort the union by ``(namespace, name)`` for determinism.
        4. For each name, call ``comparator.compare(source_obj, target_obj)``
           where either argument is ``None`` when the name is absent on that
           side.
        5. Accumulate all returned deltas into the result.
        6. Apply *ignore* rules to the completed result when provided.

        The result is a :class:`~pgschemadiff.domain.delta.DeltaSet` in a
        stable, reproducible order.  **This is NOT a topological sort** — the
        downstream ``topo_sort`` step (task P2-DIFF-08) handles dependency
        ordering.

        Parameters
        ----------
        source:
            The *current* database state (what exists now).
        target:
            The *desired* database state (what we want to reach).
        ignore:
            Optional exact-match object and attribute rules applied after
            comparison.

        Returns
        -------
        pgschemadiff.domain.delta.DeltaSet
            All deltas emitted by all registered comparators, in a
            deterministic pre-sorted order.
        """
        if renames is not None:
            if (renames.tables or renames.columns) and ObjectKind.TABLE not in self._registry:
                raise DiffError("Rename annotations require a TABLE comparator")
            renames.validate_for(source, target)

        all_deltas: list[DeltaBase] = []

        for kind, comparator in self._registry.items():
            source_objects = _fetch_objects_for_kind(source, kind)
            target_objects = _fetch_objects_for_kind(target, kind)

            if kind is ObjectKind.INDEX and renames is not None and renames.tables:
                source_index_list = [cast("Index", item) for item in source_objects.values()]
                target_index_list = [cast("Index", item) for item in target_objects.values()]
                source_indexes = {
                    (_index_pair_parent(index, renames), index.ref.qname.name): index
                    for index in source_index_list
                }
                target_indexes = {
                    (index.table_ref.qname, index.ref.qname.name): index
                    for index in target_index_list
                }
                pair_keys = sorted(
                    source_indexes.keys() | target_indexes.keys(),
                    key=lambda item: (item[0].namespace, item[0].name, item[1]),
                )
                for pair_key in pair_keys:
                    all_deltas.extend(
                        _compare_with_renames(
                            comparator,
                            source_indexes.get(pair_key),
                            target_indexes.get(pair_key),
                            renames,
                        )
                    )
                continue

            consumed_source: set[QualifiedName] = set()
            consumed_target: set[QualifiedName] = set()

            if kind is ObjectKind.TABLE and renames is not None:
                for table_rename in sorted(
                    renames.tables,
                    key=lambda item: _qname_sort_key(item.source),
                ):
                    src_obj = source_objects[table_rename.source]
                    tgt_obj = target_objects[table_rename.target]
                    all_deltas.extend(_compare_with_renames(comparator, src_obj, tgt_obj, renames))
                    consumed_source.add(table_rename.source)
                    consumed_target.add(table_rename.target)

            all_qnames = set(source_objects) | set(target_objects)
            sorted_qnames = sorted(
                all_qnames - consumed_source - consumed_target,
                key=_qname_sort_key,
            )

            for qname in sorted_qnames:
                src_obj = source_objects.get(qname)
                tgt_obj = target_objects.get(qname)
                if (
                    kind in {ObjectKind.TABLE, ObjectKind.INDEX}
                    and renames is not None
                    and (renames.tables or renames.columns)
                    and src_obj is not None
                    and tgt_obj is not None
                ):
                    emitted = _compare_with_renames(comparator, src_obj, tgt_obj, renames)
                else:
                    emitted = comparator.compare(src_obj, tgt_obj)
                all_deltas.extend(emitted)

        result = DeltaSet.from_iterable(all_deltas)
        return ignore.apply(result) if ignore is not None else result

    # ------------------------------------------------------------------
    # Introspection helpers (useful for testing + debugging)
    # ------------------------------------------------------------------

    @property
    def registered_kinds(self) -> frozenset[ObjectKind]:
        """The set of :class:`~pgschemadiff.domain.identity.ObjectKind` values
        for which a comparator has been registered."""
        return frozenset(self._registry)


def _index_pair_parent(index: Index, renames: RenameAnnotations) -> QualifiedName:
    """Map index's owning table identity for rename-aware logical pairing."""
    return renames.map_table(index.table_ref.qname)


def _compare_with_renames(
    comparator: Comparator,
    source: object | None,
    target: object | None,
    renames: RenameAnnotations,
) -> Iterable[DeltaBase]:
    """Dispatch explicit mappings only to comparators that support them."""
    if not isinstance(comparator, RenameAwareComparator):
        raise DiffError(f"Comparator for {comparator.kind!r} does not support rename annotations")
    return comparator.compare_with_renames(source, target, renames)
