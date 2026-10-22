"""Derive delta prerequisites and return a stable dependency ordering."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from pgschemadiff.application.diff.topo_sort import topological_sort
from pgschemadiff.domain.constraint import ForeignKeyConstraint
from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp, DeltaSet
from pgschemadiff.domain.delta.column import AddColumn, DropColumn, RenameColumn
from pgschemadiff.domain.delta.constraint import AddConstraint, DropConstraint
from pgschemadiff.domain.delta.index import CreateIndex, DropIndex, ReplaceIndex
from pgschemadiff.domain.delta.schema import (
    CreateExtension,
    CreateSchema,
    DropExtension,
    DropSchema,
)
from pgschemadiff.domain.delta.table import CreateTable, DropTable, RenameTable
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from pgschemadiff.domain.index import Index


def order_deltas(delta_set: DeltaSet) -> DeltaSet:
    """Return deltas ordered after their structured prerequisites."""
    nodes = delta_set.deltas
    dependencies: dict[DeltaBase, set[DeltaBase]] = {delta: set() for delta in nodes}

    def add(prerequisite: DeltaBase, dependent: DeltaBase) -> None:
        if prerequisite != dependent:
            dependencies[dependent].add(prerequisite)

    creates, drops, schema_creates = _collect_resources(nodes)
    _add_create_dependencies(nodes, creates, schema_creates, add)
    _add_drop_dependencies(nodes, drops, add)
    _add_schema_drop_dependencies(nodes, add)
    _add_rename_dependencies(nodes, add)
    return DeltaSet.from_iterable(
        topological_sort(nodes, dependencies, key=lambda delta: delta.sort_key)
    )


def _collect_resources(
    nodes: tuple[DeltaBase, ...],
) -> tuple[
    dict[ObjectRef, list[DeltaBase]],
    dict[ObjectRef, list[DeltaBase]],
    dict[str, list[DeltaBase]],
]:
    creates: dict[ObjectRef, list[DeltaBase]] = defaultdict(list)
    drops: dict[ObjectRef, list[DeltaBase]] = defaultdict(list)
    schema_creates: dict[str, list[DeltaBase]] = defaultdict(list)
    for delta in nodes:
        if isinstance(delta, CreateSchema):
            schema_creates[delta.target.qname.name].append(delta)
        elif isinstance(delta, CreateTable):
            creates[delta.table.ref].append(delta)
            for column in delta.table.columns:
                creates[_column_ref(delta.table.ref, column.name)].append(delta)
        elif isinstance(delta, (AddColumn, AddConstraint)):
            creates[delta.target].append(delta)
        elif isinstance(delta, DropTable):
            drops[delta.table.ref].append(delta)
            for column in delta.table.columns:
                drops[_column_ref(delta.table.ref, column.name)].append(delta)
        elif isinstance(delta, (DropColumn, DropConstraint)):
            drops[delta.target].append(delta)
    return creates, drops, schema_creates


def _add_create_dependencies(
    nodes: tuple[DeltaBase, ...],
    creates: dict[ObjectRef, list[DeltaBase]],
    schema_creates: dict[str, list[DeltaBase]],
    add: Callable[[DeltaBase, DeltaBase], None],
) -> None:
    for delta in nodes:
        if isinstance(delta, AddColumn):
            _add_create_prerequisites(delta, (delta.target.parent, delta.target), creates, add)
        elif isinstance(delta, AddConstraint):
            _add_constraint_create_dependencies(delta, creates, add)
        elif isinstance(delta, CreateTable):
            for constraint in delta.table.constraints:
                if isinstance(constraint, ForeignKeyConstraint):
                    _add_create_prerequisites(
                        delta, _fk_refs(constraint, delta.table.ref), creates, add
                    )

    _add_index_create_dependencies(nodes, creates, add)

    for delta in nodes:
        if delta.op is DeltaOp.CREATE and delta.target.kind not in {
            ObjectKind.SCHEMA,
            ObjectKind.EXTENSION,
        }:
            for schema_create in schema_creates.get(delta.target.qname.namespace, ()):
                add(schema_create, delta)
        elif isinstance(delta, CreateExtension) and delta.extension.installed_schema is not None:
            for schema_create in schema_creates.get(delta.extension.installed_schema, ()):
                add(schema_create, delta)


def _add_index_create_dependencies(
    nodes: tuple[DeltaBase, ...],
    creates: dict[ObjectRef, list[DeltaBase]],
    add: Callable[[DeltaBase, DeltaBase], None],
) -> None:
    for delta in nodes:
        if isinstance(delta, CreateIndex):
            _add_create_prerequisites(delta, _index_refs(delta.index), creates, add)
        elif isinstance(delta, ReplaceIndex):
            _add_create_prerequisites(delta, _index_refs(delta.new_index), creates, add)


def _add_constraint_create_dependencies(
    delta: AddConstraint,
    creates: dict[ObjectRef, list[DeltaBase]],
    add: Callable[[DeltaBase, DeltaBase], None],
) -> None:
    owner = delta.target.parent
    refs = [owner] if owner is not None else []
    if owner is not None:
        refs.extend(_column_ref(owner, name) for name in getattr(delta.constraint, "columns", ()))
    if isinstance(delta.constraint, ForeignKeyConstraint) and owner is not None:
        refs.extend(_fk_refs(delta.constraint, owner))
    _add_create_prerequisites(delta, refs, creates, add)


def _add_drop_dependencies(
    nodes: tuple[DeltaBase, ...],
    drops: dict[ObjectRef, list[DeltaBase]],
    add: Callable[[DeltaBase, DeltaBase], None],
) -> None:
    for delta in nodes:
        if isinstance(delta, DropColumn) and delta.target.parent is not None:
            _add_drop_prerequisites(delta, (delta.target.parent,), drops, add)
        elif isinstance(delta, DropConstraint):
            _add_constraint_drop_dependencies(delta, drops, add)
        elif isinstance(delta, DropIndex):
            _add_drop_prerequisites(delta, _index_refs(delta.index), drops, add)
        elif isinstance(delta, ReplaceIndex):
            _add_drop_prerequisites(delta, _index_refs(delta.old_index), drops, add)
        elif isinstance(delta, DropTable):
            for constraint in delta.table.constraints:
                if isinstance(constraint, ForeignKeyConstraint):
                    _add_drop_prerequisites(delta, _fk_remote_refs(constraint), drops, add)


def _add_constraint_drop_dependencies(
    delta: DropConstraint,
    drops: dict[ObjectRef, list[DeltaBase]],
    add: Callable[[DeltaBase, DeltaBase], None],
) -> None:
    owner = delta.target.parent
    refs = [owner] if owner is not None else []
    if owner is not None:
        refs.extend(_column_ref(owner, name) for name in getattr(delta.constraint, "columns", ()))
    if isinstance(delta.constraint, ForeignKeyConstraint) and owner is not None:
        refs.extend(_fk_refs(delta.constraint, owner))
    _add_drop_prerequisites(delta, refs, drops, add)


def _add_schema_drop_dependencies(
    nodes: tuple[DeltaBase, ...],
    add: Callable[[DeltaBase, DeltaBase], None],
) -> None:
    for delta in nodes:
        if not isinstance(delta, DropSchema):
            continue
        schema_name = delta.target.qname.name
        for other in nodes:
            if isinstance(other, DropExtension):
                if other.extension.installed_schema == schema_name:
                    add(other, delta)
            elif (
                other.op is DeltaOp.DROP
                and not isinstance(other, DropSchema)
                and other.target.qname.namespace == schema_name
            ):
                add(other, delta)


def _column_ref(table_ref: ObjectRef, name: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace=table_ref.qname.namespace, name=name),
        parent=table_ref,
    )


def _fk_table_ref(constraint: ForeignKeyConstraint) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace=constraint.ref_namespace, name=constraint.ref_table),
    )


def _fk_refs(constraint: ForeignKeyConstraint, owner: ObjectRef) -> tuple[ObjectRef, ...]:
    return (
        owner,
        *(_column_ref(owner, name) for name in constraint.columns),
        *_fk_remote_refs(constraint),
    )


def _fk_remote_refs(constraint: ForeignKeyConstraint) -> tuple[ObjectRef, ...]:
    referenced = _fk_table_ref(constraint)
    return (
        referenced,
        *(_column_ref(referenced, name) for name in constraint.ref_columns),
    )


def _index_refs(index: Index) -> tuple[ObjectRef, ...]:
    columns = [key.column_name for key in index.key_columns if key.column_name is not None]
    columns.extend(index.include_columns)
    return (index.table_ref, *(_column_ref(index.table_ref, name) for name in columns))


def _add_create_prerequisites(
    dependent: DeltaBase,
    refs: Iterable[ObjectRef | None],
    creates: dict[ObjectRef, list[DeltaBase]],
    add: Callable[[DeltaBase, DeltaBase], None],
) -> None:
    for ref in refs:
        if ref is not None:
            for prerequisite in creates.get(ref, ()):
                add(prerequisite, dependent)


def _add_drop_prerequisites(
    dependent: DeltaBase,
    refs: Iterable[ObjectRef | None],
    drops: dict[ObjectRef, list[DeltaBase]],
    add: Callable[[DeltaBase, DeltaBase], None],
) -> None:
    for ref in refs:
        if ref is not None:
            for later_drop in drops.get(ref, ()):
                add(dependent, later_drop)


def _add_rename_dependencies(
    nodes: tuple[DeltaBase, ...],
    add: Callable[[DeltaBase, DeltaBase], None],
) -> None:
    table_renames = [delta for delta in nodes if isinstance(delta, RenameTable)]
    column_renames = [delta for delta in nodes if isinstance(delta, RenameColumn)]

    for rename in table_renames:
        for delta in nodes:
            if delta != rename and rename.new_name in _referenced_tables(delta):
                add(rename, delta)

    for column_rename in column_renames:
        parent = column_rename.target.parent
        if parent is None:
            continue
        parent_names = {parent.qname}
        for table_rename in table_renames:
            if parent.qname in {table_rename.target.qname, table_rename.new_name}:
                parent_names.update({table_rename.target.qname, table_rename.new_name})
        for delta in nodes:
            if delta != column_rename and _uses_new_column(
                delta, parent_names, column_rename.new_name
            ):
                add(column_rename, delta)


def _referenced_tables(delta: DeltaBase) -> set[QualifiedName]:
    refs: set[QualifiedName] = set()
    if delta.target.kind is ObjectKind.TABLE:
        refs.add(delta.target.qname)
    if delta.target.parent is not None:
        refs.add(delta.target.parent.qname)
    if isinstance(delta, (CreateIndex, DropIndex)):
        refs.add(delta.index.table_ref.qname)
    elif isinstance(delta, ReplaceIndex):
        refs.update((delta.old_index.table_ref.qname, delta.new_index.table_ref.qname))

    if isinstance(delta, (CreateTable, DropTable)):
        constraints = delta.table.constraints
        refs.add(delta.table.ref.qname)
    elif isinstance(delta, (AddConstraint, DropConstraint)):
        constraints = (delta.constraint,)
    else:
        constraints = ()
    for constraint in constraints:
        if isinstance(constraint, ForeignKeyConstraint):
            refs.add(QualifiedName(namespace=constraint.ref_namespace, name=constraint.ref_table))
    return refs


def _uses_new_column(
    delta: DeltaBase,
    parent_names: set[QualifiedName],
    name: str,
) -> bool:
    if (
        delta.target.kind is ObjectKind.COLUMN
        and delta.target.parent is not None
        and delta.target.parent.qname in parent_names
        and delta.target.qname.name == name
    ):
        return True

    indexes: tuple[Index, ...] = ()
    if isinstance(delta, CreateIndex):
        indexes = (delta.index,)
    elif isinstance(delta, ReplaceIndex):
        indexes = (delta.new_index,)
    if any(
        index.table_ref.qname in parent_names
        and (
            any(key.column_name == name for key in index.key_columns)
            or name in index.include_columns
        )
        for index in indexes
    ):
        return True

    if isinstance(delta, CreateTable):
        owner_ref: ObjectRef | None = delta.table.ref
        constraints = delta.table.constraints
    elif isinstance(delta, AddConstraint):
        owner_ref = delta.target.parent
        constraints = (delta.constraint,)
    else:
        return False
    if (
        owner_ref is not None
        and owner_ref.qname in parent_names
        and any(name in getattr(constraint, "columns", ()) for constraint in constraints)
    ):
        return True
    return any(
        isinstance(constraint, ForeignKeyConstraint)
        and QualifiedName(
            namespace=constraint.ref_namespace,
            name=constraint.ref_table,
        )
        in parent_names
        and name in constraint.ref_columns
        for constraint in constraints
    )
