"""Table comparator — P2-DIFF-02.

Implements :class:`TableComparator`, the :class:`~pgschemadiff.application.diff.engine.Comparator`
for :attr:`~pgschemadiff.domain.identity.ObjectKind.TABLE`.

Design notes
------------
Rename is never inferred (ADR-0007)
    :class:`RenameTable` deltas are produced only when an explicit rename
    annotation is present (task P2-DIFF-06 — rename annotation loader).
    :class:`TableComparator` never emits :class:`~pgschemadiff.domain.delta.RenameTable`.

Table-level vs. structural deltas
    :class:`TableComparator` is responsible for **table-level** deltas only:

    * :class:`~pgschemadiff.domain.delta.CreateTable` — new table in target only.
    * :class:`~pgschemadiff.domain.delta.DropTable` — table removed from source.
    * :class:`~pgschemadiff.domain.delta.AlterTableAttrs` — owner / tablespace /
      comment / partition metadata changed.

    Structural sub-object diffs (columns, constraints) are **delegated** to
    injected sub-comparators (see *Dependency injection* below).

Indexes are NOT delegated here
    Indexes are top-level objects in pgschemadiff's object model.  They are
    diffed by :class:`~pgschemadiff.application.diff.comparators.index.IndexComparator`
    dispatched through the :class:`~pgschemadiff.application.diff.engine.DiffEngine`
    for :attr:`~pgschemadiff.domain.identity.ObjectKind.INDEX`.
    :class:`TableComparator` does not touch indexes.

Dependency injection (DI)
    The column comparator (P2-DIFF-03) and constraint comparator (P2-DIFF-05)
    are separate tasks being developed in parallel.  To keep this module
    independently testable and decoupled, they are accepted as optional
    collaborators in the constructor typed via local structural Protocols
    (:class:`ColumnComparing` and :class:`ConstraintComparing`).

    When a sub-comparator is ``None`` the delegation step is skipped silently;
    table-level deltas are still emitted.  Once P2-DIFF-03 and P2-DIFF-05 land,
    callers wire them at construction time.

Deterministic output ordering
    For any ``(source, target)`` pair where both are present, the method returns
    deltas in the following stable order:

    1. Table-level delta(s) — zero or one :class:`~pgschemadiff.domain.delta.AlterTableAttrs`.
    2. Column deltas — returned by the injected ``column_comparator`` (if any).
    3. Constraint deltas — returned by the injected ``constraint_comparator`` (if any).

Layer contract
    Pure application layer: no IO, no async, no psycopg, no infra/presentation
    imports.  Depends only on :mod:`pgschemadiff.domain` and stdlib.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

from pgschemadiff.domain.delta import AlterTableAttrs, CreateTable, DropTable, RenameTable
from pgschemadiff.domain.identity import ObjectKind, QualifiedName
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from pgschemadiff.application.diff.renames import RenameAnnotations
    from pgschemadiff.domain.column import Column
    from pgschemadiff.domain.constraint import Constraint
    from pgschemadiff.domain.delta.base import DeltaBase
    from pgschemadiff.domain.identity import ObjectRef
    from pgschemadiff.domain.table import Table


# ---------------------------------------------------------------------------
# Local structural Protocols for injected sub-comparators
# ---------------------------------------------------------------------------


@runtime_checkable
class ColumnComparing(Protocol):
    """Structural interface for the column sub-comparator (P2-DIFF-03).

    :class:`TableComparator` calls :meth:`compare_columns` with the parent
    table reference and the two column tuples when both source and target
    tables are present.  The column comparator returns a tuple of column-level
    :class:`~pgschemadiff.domain.delta.base.DeltaBase` subclasses in the order
    it deems deterministic.

    This Protocol is intentionally defined here so that :class:`TableComparator`
    can be tested in isolation using a stub implementation.  The concrete
    :class:`~pgschemadiff.application.diff.comparators.column.ColumnComparator`
    satisfies this protocol structurally.
    """

    def compare_columns(
        self,
        table_ref: ObjectRef,
        source_columns: tuple[Column, ...],
        target_columns: tuple[Column, ...],
    ) -> tuple[DeltaBase, ...]:
        """Compare two column tuples and return the resulting column deltas."""
        ...


@runtime_checkable
class ConstraintComparing(Protocol):
    """Structural interface for the constraint sub-comparator (P2-DIFF-05).

    :class:`TableComparator` calls :meth:`compare_sets` with the parent table
    reference and both constraint tuples when both source and target tables are
    present.  The constraint comparator returns a tuple of constraint-level
    :class:`~pgschemadiff.domain.delta.base.DeltaBase` subclasses.

    The method name ``compare_sets`` matches the API that P2-DIFF-05
    (``ConstraintComparator``) is implementing, allowing zero-change wiring.
    """

    def compare_sets(
        self,
        table_ref: ObjectRef,
        source_constraints: tuple[Constraint, ...],
        target_constraints: tuple[Constraint, ...],
    ) -> tuple[DeltaBase, ...]:
        """Compare two constraint tuples and return the resulting constraint deltas."""
        ...


class RenameAwareColumnComparing(Protocol):
    """Optional column-comparator capability for explicit rename pairs."""

    def compare_columns_with_renames(
        self,
        source_table_ref: ObjectRef,
        target_table_ref: ObjectRef,
        source_columns: tuple[Column, ...],
        target_columns: tuple[Column, ...],
        renames: dict[str, str],
    ) -> tuple[DeltaBase, ...]:
        """Compare table columns using explicit source-to-target names."""
        ...


class RenameAwareConstraintComparing(Protocol):
    """Optional constraint-comparator capability for explicit references."""

    def compare_with_renames(
        self,
        source_table_ref: ObjectRef,
        target_table_ref: ObjectRef,
        source_constraints: tuple[Constraint, ...],
        target_constraints: tuple[Constraint, ...],
        renames: RenameAnnotations,
    ) -> tuple[DeltaBase, ...]:
        """Compare constraints using explicit local and referenced mappings."""
        ...


# ---------------------------------------------------------------------------
# TableComparator
# ---------------------------------------------------------------------------


class TableComparator:
    """Comparator for :attr:`~pgschemadiff.domain.identity.ObjectKind.TABLE`.

    Satisfies the :class:`~pgschemadiff.application.diff.engine.Comparator`
    Protocol structurally (duck-typed): it declares ``kind = ObjectKind.TABLE``
    and ``compare(source, target) -> tuple[DeltaBase, ...]``.

    Parameters
    ----------
    column_comparator:
        Optional injected collaborator implementing :class:`ColumnComparing`.
        When provided, column-level diffs are delegated to it.  When ``None``,
        the column delegation step is skipped (only table-level deltas are
        emitted for the modified-table case).
    constraint_comparator:
        Optional injected collaborator implementing :class:`ConstraintComparing`.
        When provided, constraint-level diffs are delegated to it.  When
        ``None``, the constraint delegation step is skipped.
    """

    kind: ObjectKind = ObjectKind.TABLE

    def __init__(
        self,
        *,
        column_comparator: ColumnComparing | None = None,
        constraint_comparator: ConstraintComparing | None = None,
    ) -> None:
        self._column_comparator = column_comparator
        self._constraint_comparator = constraint_comparator

    # ------------------------------------------------------------------
    # Comparator Protocol implementation
    # ------------------------------------------------------------------

    def compare(
        self,
        source: object | None,
        target: object | None,
    ) -> tuple[DeltaBase, ...]:
        """Compare one ``(source, target)`` table pair and return emitted deltas.

        Parameters
        ----------
        source:
            The :class:`~pgschemadiff.domain.table.Table` as it exists in the
            *source* (current) database, or ``None`` when the table does not
            exist in the source.
        target:
            The :class:`~pgschemadiff.domain.table.Table` as it exists in the
            *target* (desired) database, or ``None`` when the table does not
            exist in the target.

        Returns
        -------
        tuple[DeltaBase, ...]
            * ``source is None, target set`` →
              ``(CreateTable(target=target.ref, table=target),)``
              The table is created whole — its columns and constraints travel
              with it.  No per-column or per-constraint deltas are emitted in
              this case.
            * ``source set, target is None`` →
              ``(DropTable(target=source.ref, table=source),)``
            * ``both set`` → table-level attr delta (if any) + delegated column
              deltas + delegated constraint deltas (in that order).
            * ``both None`` → ``()``.

        Notes
        -----
        Rename is never inferred (ADR-0007): :class:`RenameTable` is never
        emitted here.  It is produced only by the rename-annotation loader
        (task P2-DIFF-06) when an explicit annotation is present.

        Indexes are NOT emitted here.  They are top-level objects handled by
        the :class:`~pgschemadiff.application.diff.comparators.index.IndexComparator`
        via the :class:`~pgschemadiff.application.diff.engine.DiffEngine`.
        """
        # Narrow types from Protocol's broad ``object | None``
        src: Table | None = source  # type: ignore[assignment]
        tgt: Table | None = target  # type: ignore[assignment]

        if src is None and tgt is None:
            return ()

        if src is None:
            # Table exists only in target → CREATE
            assert tgt is not None  # narrowed above
            return (CreateTable(target=tgt.ref, table=tgt),)

        if tgt is None:
            # Table exists only in source → DROP
            assert src is not None  # narrowed above
            return (DropTable(target=src.ref, table=src),)

        # Both tables present — emit table-level attrs delta + delegate sub-objects
        return self._compare_both(src, tgt)

    def compare_with_renames(
        self,
        source: object | None,
        target: object | None,
        renames: RenameAnnotations,
    ) -> tuple[DeltaBase, ...]:
        """Compare a pair selected by explicit table/column annotations."""
        src: Table | None = source  # type: ignore[assignment]
        tgt: Table | None = target  # type: ignore[assignment]
        if src is None or tgt is None:
            return self.compare(src, tgt)

        table_rename = renames.table_target(src.ref.qname) == tgt.ref.qname
        if src.ref.qname != tgt.ref.qname and not table_rename:
            raise DiffError(
                f"Table pair {src.ref.qname.fqn} -> {tgt.ref.qname.fqn} has no explicit annotation"
            )

        result: list[DeltaBase] = []
        if table_rename:
            result.append(
                RenameTable(
                    target=src.ref,
                    old_name=src.ref.qname,
                    new_name=tgt.ref.qname,
                )
            )
        result.extend(self._compare_both(src, tgt, renames=renames))
        return tuple(result)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compare_both(
        self,
        source: Table,
        target: Table,
        *,
        renames: RenameAnnotations | None = None,
    ) -> tuple[DeltaBase, ...]:
        """Handle the case where both source and target tables exist.

        Emits deltas in deterministic order:
        1. Table-level attribute delta (:class:`~pgschemadiff.domain.delta.AlterTableAttrs`) if any.
        2. Column deltas (delegated to ``column_comparator`` if provided).
        3. Constraint deltas (delegated to ``constraint_comparator`` if provided).
        """
        result: list[DeltaBase] = []

        # --- Table-level attribute comparison ---
        attr_delta = self._build_attr_delta(source, target, renames=renames)
        if attr_delta is not None:
            result.append(attr_delta)

        result.extend(self._compare_columns(source, target, renames))
        result.extend(self._compare_constraints(source, target, renames))
        return tuple(result)

    def _compare_columns(
        self,
        source: Table,
        target: Table,
        renames: RenameAnnotations | None,
    ) -> tuple[DeltaBase, ...]:
        """Delegate column pairing, passing explicit mappings when present."""
        column_renames = (
            renames.column_targets(source.ref.qname, target.ref.qname)
            if renames is not None
            else {}
        )
        if self._column_comparator is None:
            if renames is not None and (column_renames or source.columns != target.columns):
                raise DiffError("Rename-aware table comparison requires a column comparator")
            return ()

        if renames is not None and (column_renames or source.ref != target.ref):
            compare_with_renames = getattr(
                self._column_comparator,
                "compare_columns_with_renames",
                None,
            )
            if not callable(compare_with_renames):
                raise DiffError("Column comparator does not support rename annotations")
            return cast(
                "RenameAwareColumnComparing", self._column_comparator
            ).compare_columns_with_renames(
                source.ref,
                target.ref,
                source.columns,
                target.columns,
                column_renames,
            )

        return self._column_comparator.compare_columns(
            source.ref,
            source.columns,
            target.columns,
        )

    def _compare_constraints(
        self,
        source: Table,
        target: Table,
        renames: RenameAnnotations | None,
    ) -> tuple[DeltaBase, ...]:
        """Delegate constraint comparison, normalizing mapped references."""
        if self._constraint_comparator is None:
            if renames is not None and source.constraints != target.constraints:
                raise DiffError("Rename-aware table comparison requires a constraint comparator")
            return ()

        if renames is not None:
            compare_with_renames = getattr(
                self._constraint_comparator,
                "compare_with_renames",
                None,
            )
            if callable(compare_with_renames):
                return cast(
                    "RenameAwareConstraintComparing",
                    self._constraint_comparator,
                ).compare_with_renames(
                    source.ref,
                    target.ref,
                    source.constraints,
                    target.constraints,
                    renames,
                )
            if source.constraints == target.constraints:
                return ()
            raise DiffError("Constraint comparator does not support rename annotations")

        return self._constraint_comparator.compare_sets(
            target.ref,
            source.constraints,
            target.constraints,
        )

    @staticmethod
    def _build_attr_delta(
        source: Table,
        target: Table,
        *,
        renames: RenameAnnotations | None = None,
    ) -> AlterTableAttrs | None:
        """Build an :class:`~pgschemadiff.domain.delta.AlterTableAttrs` when any
        table-level attribute differs between *source* and *target*.

        Only the fields that actually changed are populated; fields that have
        not changed are left as ``None``.  Returns ``None`` (no delta) when all
        attributes are identical — this avoids constructing an all-``None``
        :class:`~pgschemadiff.domain.delta.AlterTableAttrs` that the validator
        would reject.

        Attributes compared (all are pure table-level; structural changes live
        in column / constraint deltas):

        * ``owner``
        * ``tablespace``
        * ``comment``
        * ``partition_info``
        * ``partition_of``
        """
        new_owner = target.owner if target.owner != source.owner else None
        new_tablespace = target.tablespace if target.tablespace != source.tablespace else None
        new_comment = target.comment if target.comment != source.comment else None
        new_partition_info = (
            target.partition_info if target.partition_info != source.partition_info else None
        )
        source_partition_of = source.partition_of
        if source_partition_of is not None and renames is not None:
            source_parent = QualifiedName(
                namespace=source_partition_of.parent_namespace,
                name=source_partition_of.parent_name,
            )
            target_parent = renames.map_table(source_parent)
            if target_parent != source_parent:
                source_partition_of = source_partition_of.model_copy(
                    update={
                        "parent_namespace": target_parent.namespace,
                        "parent_name": target_parent.name,
                    }
                )
        new_partition_of = (
            target.partition_of if target.partition_of != source_partition_of else None
        )

        # Nothing changed → no delta
        if (
            new_owner is None
            and new_tablespace is None
            and new_comment is None
            and new_partition_info is None
            and new_partition_of is None
        ):
            return None

        return AlterTableAttrs(
            target=target.ref,
            new_owner=new_owner,
            new_tablespace=new_tablespace,
            new_comment=new_comment,
            new_partition_info=new_partition_info,
            new_partition_of=new_partition_of,
        )


__all__ = [
    "ColumnComparing",
    "ConstraintComparing",
    "TableComparator",
]
