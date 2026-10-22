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
        """Compare two column tuples and return deterministic column deltas.

        Columns present on only one side emit ``AddColumn`` or ``DropColumn``.
        Results are ordered by column position (name breaks position ties).
        Same-name columns emit supported attribute deltas in type, default,
        then nullability order.  A different name is treated as independent
        add/drop operations; rename inference is intentionally avoided.
        """
        source_by_name = {column.name: column for column in source_columns}
        target_by_name = {column.name: column for column in target_columns}
        columns_by_name = source_by_name | target_by_name
        result: list[DeltaBase] = []

        for name in sorted(
            columns_by_name,
            key=lambda column_name: (columns_by_name[column_name].position, column_name),
        ):
            source = source_by_name.get(name)
            target = target_by_name.get(name)
            column_ref = self._make_ref(table_ref, name)

            if source is None:
                assert target is not None
                result.append(AddColumn(target=column_ref, column=target))
                continue

            if target is None:
                result.append(DropColumn(target=column_ref, column=source))
                continue

            if source.position != target.position:
                raise DiffError(f"Unsupported column position change for {column_ref.qname.fqn}")
            if source.identity != target.identity:
                raise DiffError(f"Unsupported identity change for {column_ref.qname.fqn}")
            if source.generated_expression != target.generated_expression:
                raise DiffError(
                    f"Unsupported generated_expression change for {column_ref.qname.fqn}"
                )
            if source.collation != target.collation and target.collation is None:
                raise DiffError(f"Unsupported collation removal for {column_ref.qname.fqn}")

            collation_changed = source.collation != target.collation
            if source.data_type != target.data_type or collation_changed:
                result.append(
                    AlterColumnType(
                        target=column_ref,
                        new_data_type=target.data_type,
                        new_collation=target.collation if collation_changed else None,
                    )
                )

            if source.default_expr != target.default_expr:
                result.append(SetColumnDefault(target=column_ref, new_default=target.default_expr))

            if source.nullable != target.nullable:
                result.append(SetColumnNullability(target=column_ref, nullable=target.nullable))

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
