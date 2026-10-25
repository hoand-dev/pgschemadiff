"""Column comparator — sub-object diff for table columns (task P2-DIFF-03).

Columns are compared by exact name and emitted in stable position order. Renames
are not inferred; explicit rename annotations are handled separately.  Changes
to metadata without a representable delta raise :class:`DiffError` rather than
being silently discarded.

This comparator is a table sub-object collaborator, not a top-level
``DiffEngine`` comparator.  It satisfies :class:`ColumnComparing` and is
delegated to by :class:`TableComparator`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.domain.delta.column import (
    AddColumn,
    AlterColumnType,
    DropColumn,
    RenameColumn,
    SetColumnDefault,
    SetColumnNullability,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.shared.errors import DiffError

if TYPE_CHECKING:
    from pgschemadiff.domain.column import Column
    from pgschemadiff.domain.delta.base import DeltaBase


class ColumnComparator:
    """Compare columns belonging to one table snapshot pair.

    Same-name columns support type, collation assignment, default, and
    nullability changes.  Position, identity, generated-expression, and
    collation-removal changes currently have no complete delta representation
    and raise :class:`DiffError`.
    """

    kind: ObjectKind = ObjectKind.COLUMN

    def compare_columns(
        self,
        table_ref: ObjectRef,
        source_columns: tuple[Column, ...],
        target_columns: tuple[Column, ...],
    ) -> tuple[DeltaBase, ...]:
        """Compare columns without rename annotations."""
        return self.compare_columns_with_renames(
            table_ref,
            table_ref,
            source_columns,
            target_columns,
            {},
        )

    def compare_columns_with_renames(
        self,
        source_table_ref: ObjectRef,
        target_table_ref: ObjectRef,
        source_columns: tuple[Column, ...],
        target_columns: tuple[Column, ...],
        renames: dict[str, str],
    ) -> tuple[DeltaBase, ...]:
        """Compare two column tuples and return deterministic column deltas.

        Explicit mappings pair renamed columns; all other names retain normal
        add/drop matching. Alterations after a rename target the target table
        and column identity, while ``RenameColumn`` targets the source identity.
        """
        source_by_name = {column.name: column for column in source_columns}
        target_by_name = {column.name: column for column in target_columns}
        if len(set(renames.values())) != len(renames):
            raise DiffError("Multiple column renames target the same column")

        pairs: list[tuple[Column | None, Column | None]] = []
        renamed_sources = set(renames)
        renamed_targets = set(renames.values())
        for source_name, target_name in renames.items():
            source = source_by_name.get(source_name)
            target = target_by_name.get(target_name)
            if source is None or target is None:
                raise DiffError(
                    f"Annotated column rename {source_name!r} -> {target_name!r} not found"
                )
            pairs.append((source, target))

        same_names = (
            (source_by_name.keys() & target_by_name.keys()) - renamed_sources - renamed_targets
        )
        pairs.extend((source_by_name[name], target_by_name[name]) for name in same_names)
        pairs.extend(
            (source_by_name[name], None)
            for name in source_by_name.keys() - renamed_sources - same_names
        )
        pairs.extend(
            (None, target_by_name[name])
            for name in target_by_name.keys() - renamed_targets - same_names
        )

        def _pair_sort_key(pair: tuple[Column | None, Column | None]) -> tuple[int, str]:
            column = pair[1] if pair[1] is not None else pair[0]
            assert column is not None
            return column.position, column.name

        pairs.sort(key=_pair_sort_key)

        result: list[DeltaBase] = []
        for source, target in pairs:
            result.extend(self._compare_pair(source, target, source_table_ref, target_table_ref))

        return tuple(result)

    def _compare_pair(
        self,
        source: Column | None,
        target: Column | None,
        source_table_ref: ObjectRef,
        target_table_ref: ObjectRef,
    ) -> tuple[DeltaBase, ...]:
        """Compare one already-matched source/target column pair."""
        if source is None:
            assert target is not None
            target_ref = self._make_ref(target_table_ref, target.name)
            return (AddColumn(target=target_ref, column=target),)

        if target is None:
            source_ref = self._make_ref(source_table_ref, source.name)
            return (DropColumn(target=source_ref, column=source),)

        target_ref = self._make_ref(target_table_ref, target.name)
        result: list[DeltaBase] = []
        if source.name != target.name:
            result.append(
                RenameColumn(
                    target=self._make_ref(source_table_ref, source.name),
                    old_name=source.name,
                    new_name=target.name,
                )
            )

        if source.position != target.position:
            raise DiffError(f"Unsupported column position change for {target_ref.qname.fqn}")
        if source.identity != target.identity:
            raise DiffError(f"Unsupported identity change for {target_ref.qname.fqn}")
        if (
            source.generated_expression != target.generated_expression
            or source.generated_kind != target.generated_kind
        ):
            raise DiffError(f"Unsupported generated_expression change for {target_ref.qname.fqn}")
        if source.collation != target.collation and target.collation is None:
            raise DiffError(f"Unsupported collation removal for {target_ref.qname.fqn}")

        collation_changed = source.collation != target.collation
        if source.data_type != target.data_type or collation_changed:
            result.append(
                AlterColumnType(
                    target=target_ref,
                    new_data_type=target.data_type,
                    new_collation=target.collation if collation_changed else None,
                )
            )

        if source.default_expr != target.default_expr:
            result.append(SetColumnDefault(target=target_ref, new_default=target.default_expr))

        if source.nullable != target.nullable:
            result.append(SetColumnNullability(target=target_ref, nullable=target.nullable))
        return tuple(result)

    @staticmethod
    def _make_ref(table_ref: ObjectRef, column_name: str) -> ObjectRef:
        """Build a column reference scoped to its owning table."""
        return ObjectRef(
            kind=ObjectKind.COLUMN,
            qname=QualifiedName(namespace=table_ref.qname.namespace, name=column_name),
            parent=table_ref,
        )


__all__ = ["ColumnComparator"]
