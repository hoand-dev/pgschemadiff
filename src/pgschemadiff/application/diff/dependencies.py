"""Derive delta prerequisites and return a stable dependency ordering."""

from __future__ import annotations

from collections import defaultdict
from itertools import pairwise
from typing import TYPE_CHECKING

from pgschemadiff.application.diff.topo_sort import topological_sort
from pgschemadiff.domain.constraint import (
    Constraint,
    ExclusionConstraint,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    UniqueConstraint,
)
from pgschemadiff.domain.delta.base import DeltaBase, DeltaOp, DeltaSet
from pgschemadiff.domain.delta.column import (
    AddColumn,
    AlterColumnType,
    DropColumn,
    RenameColumn,
    SetColumnDefault,
)
from pgschemadiff.domain.delta.composite_type import (
    AlterCompositeAddAttribute,
    AlterCompositeAttributeType,
    AlterCompositeDropAttribute,
    CreateCompositeType,
    DropCompositeType,
)
from pgschemadiff.domain.delta.constraint import AddConstraint, DropConstraint
from pgschemadiff.domain.delta.domain_type import (
    AddDomainCheck,
    AlterDomainDefault,
    AlterDomainNullability,
    CreateDomain,
    DropDomain,
    DropDomainCheck,
    ValidateDomainCheck,
)
from pgschemadiff.domain.delta.enum import AddEnumValue, CreateEnum, DropEnum
from pgschemadiff.domain.delta.index import CreateIndex, DropIndex, ReplaceIndex
from pgschemadiff.domain.delta.schema import (
    AlterExtension,
    CreateExtension,
    CreateSchema,
    DropExtension,
    DropSchema,
)
from pgschemadiff.domain.delta.sequence import (
    AlterSequenceOwnedBy,
    AlterSequenceOwner,
    CreateSequence,
    DropSequence,
)
from pgschemadiff.domain.delta.table import CreateTable, DropTable, RenameTable
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from pgschemadiff.domain.index import Index


def order_deltas(delta_set: DeltaSet) -> DeltaSet:
    """Return deltas ordered after their structured prerequisites."""
    nodes = _omit_implicitly_dropped_sequences(delta_set.deltas)
    dependencies: dict[DeltaBase, set[DeltaBase]] = {delta: set() for delta in nodes}

    def add(prerequisite: DeltaBase, dependent: DeltaBase) -> None:
        if prerequisite != dependent:
            dependencies[dependent].add(prerequisite)

    creates, drops, schema_creates = _collect_resources(nodes)
    _add_create_dependencies(nodes, creates, schema_creates, add)
    _add_enum_dependencies(nodes, add)
    _add_drop_dependencies(nodes, drops, add)
    _add_schema_drop_dependencies(nodes, add)
    _add_rename_dependencies(nodes, add)
    return DeltaSet.from_iterable(
        topological_sort(nodes, dependencies, key=lambda delta: delta.sort_key)
    )


def _omit_implicitly_dropped_sequences(nodes: tuple[DeltaBase, ...]) -> tuple[DeltaBase, ...]:
    dropped_tables = {delta.table.ref for delta in nodes if isinstance(delta, DropTable)}
    dropped_columns = {delta.target for delta in nodes if isinstance(delta, DropColumn)}
    return tuple(
        delta
        for delta in nodes
        if not (
            isinstance(delta, DropSequence)
            and delta.sequence.owned_by is not None
            and (
                delta.sequence.owned_by in dropped_columns
                or delta.sequence.owned_by.parent in dropped_tables
            )
        )
    )


def _add_enum_dependencies(
    nodes: tuple[DeltaBase, ...],
    add: Callable[[DeltaBase, DeltaBase], None],
) -> None:
    enum_changes = tuple(delta for delta in nodes if isinstance(delta, (CreateEnum, AddEnumValue)))
    table_changes = tuple(
        delta
        for delta in nodes
        if isinstance(
            delta,
            (
                CreateTable,
                AddColumn,
                AlterColumnType,
                SetColumnDefault,
                AddConstraint,
                CreateIndex,
                ReplaceIndex,
                CreateCompositeType,
                AlterCompositeAddAttribute,
                AlterCompositeAttributeType,
                CreateDomain,
                AlterDomainDefault,
                AlterDomainNullability,
                AddDomainCheck,
                ValidateDomainCheck,
            ),
        )
    )
    for enum_change in enum_changes:
        for table_change in table_changes:
            add(enum_change, table_change)

    _add_enum_addition_dependencies(nodes, add)
    _add_enum_drop_dependencies(nodes, add)


def _add_enum_addition_dependencies(
    nodes: tuple[DeltaBase, ...],
    add: Callable[[DeltaBase, DeltaBase], None],
) -> None:
    additions_by_ref: dict[ObjectRef, list[AddEnumValue]] = defaultdict(list)
    creates_by_ref: dict[ObjectRef, list[CreateEnum]] = defaultdict(list)
    for delta in nodes:
        if isinstance(delta, CreateEnum):
            creates_by_ref[delta.target].append(delta)
        elif isinstance(delta, AddEnumValue):
            additions_by_ref[delta.target].append(delta)
    for enum_ref, additions in additions_by_ref.items():
        for enum_create in creates_by_ref.get(enum_ref, ()):
            for addition in additions:
                add(enum_create, addition)
        for previous, following in pairwise(additions):
            add(previous, following)


def _add_enum_drop_dependencies(
    nodes: tuple[DeltaBase, ...],
    add: Callable[[DeltaBase, DeltaBase], None],
) -> None:
    enum_drops = tuple(delta for delta in nodes if isinstance(delta, DropEnum))
    dependent_drops = tuple(
        delta
        for delta in nodes
        if isinstance(
            delta,
            (
                DropTable,
                DropColumn,
                AlterColumnType,
                SetColumnDefault,
                DropConstraint,
                DropIndex,
                DropDomain,
                DropDomainCheck,
            ),
        )
    )
    for enum_drop in enum_drops:
        for dependent_drop in dependent_drops:
            add(dependent_drop, enum_drop)


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
        elif isinstance(
            delta,
            (
                CreateEnum,
                CreateCompositeType,
                CreateDomain,
                CreateSequence,
                AddColumn,
                AddConstraint,
            ),
        ):
            creates[delta.target].append(delta)
        elif isinstance(delta, DropTable):
            drops[delta.table.ref].append(delta)
            for column in delta.table.columns:
                drops[_column_ref(delta.table.ref, column.name)].append(delta)
        elif isinstance(
            delta,
            (DropColumn, DropConstraint, DropEnum, DropCompositeType, DropDomain, DropSequence),
        ):
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
            _add_create_prerequisites(
                delta,
                (delta.target.parent, delta.target, *delta.column.sequence_prerequisites),
                creates,
                add,
            )
        elif isinstance(delta, AddConstraint):
            _add_constraint_create_dependencies(delta, creates, add)
        elif isinstance(delta, CreateTable):
            sequence_prerequisites = tuple(
                ref for column in delta.table.columns for ref in column.sequence_prerequisites
            )
            _add_create_prerequisites(
                delta,
                (*delta.table.type_prerequisites, *sequence_prerequisites),
                creates,
                add,
            )
            partition_of = delta.table.partition_of
            if partition_of is not None:
                parent_ref = ObjectRef(
                    kind=ObjectKind.TABLE,
                    qname=QualifiedName(
                        namespace=partition_of.parent_namespace,
                        name=partition_of.parent_name,
                    ),
                )
                _add_create_prerequisites(delta, (parent_ref,), creates, add)
        elif isinstance(delta, SetColumnDefault):
            _add_create_prerequisites(delta, delta.new_sequence_prerequisites, creates, add)

    _add_sequence_dependencies(nodes, creates, add)
    _add_composite_create_dependencies(nodes, creates, add)
    _add_domain_create_dependencies(nodes, creates, add)
    _add_index_create_dependencies(nodes, creates, add)
    _add_fk_unique_dependencies(nodes, add)
    _add_constraint_identity_dependencies(nodes, add)

    for delta in nodes:
        if delta.op is DeltaOp.CREATE and delta.target.kind not in {
            ObjectKind.SCHEMA,
            ObjectKind.EXTENSION,
        }:
            for schema_create in schema_creates.get(delta.target.qname.namespace, ()):
                add(schema_create, delta)
        elif isinstance(delta, (CreateExtension, AlterExtension)):
            schema_name = (
                delta.extension.installed_schema
                if isinstance(delta, CreateExtension)
                else delta.new_schema
            )
            if schema_name is not None:
                for schema_create in schema_creates.get(schema_name, ()):
                    add(schema_create, delta)


def _add_sequence_dependencies(
    nodes: tuple[DeltaBase, ...],
    creates: dict[ObjectRef, list[DeltaBase]],
    add: Callable[[DeltaBase, DeltaBase], None],
) -> None:
    owners_by_ref: dict[ObjectRef, list[AlterSequenceOwner]] = defaultdict(list)
    for delta in nodes:
        if isinstance(delta, AlterSequenceOwner):
            owners_by_ref[delta.target].append(delta)

    for delta in nodes:
        if isinstance(delta, AlterSequenceOwnedBy):
            _add_create_prerequisites(
                delta,
                (delta.target, delta.new_owned_by),
                creates,
                add,
            )
            if delta.new_owned_by is not None:
                for owner_change in owners_by_ref.get(delta.target, ()):
                    # OWNED BY requires sequence and destination table owners to match.
                    add(owner_change, delta)


def _add_composite_create_dependencies(
    nodes: tuple[DeltaBase, ...],
    creates: dict[ObjectRef, list[DeltaBase]],
    add: Callable[[DeltaBase, DeltaBase], None],
) -> None:
    for delta in nodes:
        if isinstance(delta, CreateCompositeType):
            _add_create_prerequisites(delta, delta.composite.type_prerequisites, creates, add)
        elif isinstance(delta, AlterCompositeAddAttribute):
            _add_create_prerequisites(delta, delta.type_prerequisites, creates, add)
        elif isinstance(delta, AlterCompositeAttributeType):
            _add_create_prerequisites(delta, delta.new_type_prerequisites, creates, add)


def _add_domain_create_dependencies(
    nodes: tuple[DeltaBase, ...],
    creates: dict[ObjectRef, list[DeltaBase]],
    add: Callable[[DeltaBase, DeltaBase], None],
) -> None:
    domain_creates = tuple(delta for delta in nodes if isinstance(delta, CreateDomain))
    for delta in domain_creates:
        _add_create_prerequisites(delta, delta.domain.type_prerequisites, creates, add)

    # ponytail: order all column DDL around domain DDL; exact column type refs
    # require per-column catalog prerequisites, which this snapshot does not carry.
    column_changes = tuple(
        delta
        for delta in nodes
        if isinstance(delta, (AddColumn, AlterColumnType, SetColumnDefault))
    )
    domain_drops = tuple(delta for delta in nodes if isinstance(delta, DropDomain))
    column_removals = tuple(
        delta
        for delta in nodes
        if isinstance(delta, (DropTable, DropColumn, AlterColumnType, SetColumnDefault))
    )
    for domain_create in domain_creates:
        for column_change in column_changes:
            add(domain_create, column_change)
    for domain_drop in domain_drops:
        for column_removal in column_removals:
            add(column_removal, domain_drop)


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


def _add_fk_unique_dependencies(
    nodes: tuple[DeltaBase, ...],
    add: Callable[[DeltaBase, DeltaBase], None],
) -> None:
    unique_creates: dict[tuple[ObjectRef, frozenset[str]], list[AddConstraint]] = defaultdict(list)
    for delta in nodes:
        if not isinstance(delta, AddConstraint):
            continue
        owner = delta.target.parent
        if owner is None:
            continue
        if isinstance(delta.constraint, (PrimaryKeyConstraint, UniqueConstraint)):
            unique_creates[(owner, frozenset(delta.constraint.columns))].append(delta)

    for delta in nodes:
        if not isinstance(delta, AddConstraint) or not isinstance(
            delta.constraint, ForeignKeyConstraint
        ):
            continue
        # A FK can reference the same unique column set in a different order.
        key = (_fk_table_ref(delta.constraint), frozenset(delta.constraint.ref_columns))
        for unique_create in unique_creates.get(key, ()):
            add(unique_create, delta)


def _add_constraint_identity_dependencies(
    nodes: tuple[DeltaBase, ...],
    add: Callable[[DeltaBase, DeltaBase], None],
) -> None:
    additions: list[AddConstraint] = []
    drops_by_ref: dict[ObjectRef, list[DropConstraint]] = defaultdict(list)
    create_indexes: dict[ObjectRef, list[CreateIndex]] = defaultdict(list)
    drop_indexes: dict[ObjectRef, list[DropIndex]] = defaultdict(list)

    for delta in nodes:
        if isinstance(delta, AddConstraint):
            additions.append(delta)
        elif isinstance(delta, DropConstraint):
            drops_by_ref[delta.target].append(delta)
        elif isinstance(delta, CreateIndex):
            create_indexes[delta.target].append(delta)
        elif isinstance(delta, DropIndex):
            drop_indexes[delta.target].append(delta)

    _add_constraint_add_identity_dependencies(additions, drops_by_ref, drop_indexes, add)
    _add_drop_constraint_index_dependencies(drops_by_ref, create_indexes, add)


def _add_constraint_add_identity_dependencies(
    additions: list[AddConstraint],
    drops_by_ref: dict[ObjectRef, list[DropConstraint]],
    drop_indexes: dict[ObjectRef, list[DropIndex]],
    add: Callable[[DeltaBase, DeltaBase], None],
) -> None:
    for delta in additions:
        for dropped_constraint in drops_by_ref.get(delta.target, ()):
            add(dropped_constraint, delta)

        backing_index_ref = _constraint_backing_index_ref(delta.constraint, delta.target.parent)
        if backing_index_ref is not None:
            for dropped_index in drop_indexes.get(backing_index_ref, ()):
                add(dropped_index, delta)


def _add_drop_constraint_index_dependencies(
    drops_by_ref: dict[ObjectRef, list[DropConstraint]],
    create_indexes: dict[ObjectRef, list[CreateIndex]],
    add: Callable[[DeltaBase, DeltaBase], None],
) -> None:
    for dropped_constraints in drops_by_ref.values():
        for dropped_constraint in dropped_constraints:
            backing_index_ref = _constraint_backing_index_ref(
                dropped_constraint.constraint, dropped_constraint.target.parent
            )
            if backing_index_ref is not None:
                for created_index in create_indexes.get(backing_index_ref, ()):
                    add(dropped_constraint, created_index)


def _constraint_backing_index_ref(
    constraint: Constraint,
    owner: ObjectRef | None,
) -> ObjectRef | None:
    """Return backing-index identity.

    PostgreSQL names indexes backing PK/UNIQUE/EXCLUSION constraints after the
    constraint.
    """
    if owner is None or not isinstance(
        constraint, (PrimaryKeyConstraint, UniqueConstraint, ExclusionConstraint)
    ):
        return None
    return ObjectRef(
        kind=ObjectKind.INDEX,
        qname=QualifiedName(namespace=owner.qname.namespace, name=constraint.name),
    )


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
            _add_drop_prerequisites(
                delta,
                (delta.target.parent, *delta.column.sequence_prerequisites),
                drops,
                add,
            )
        elif isinstance(delta, AlterCompositeDropAttribute):
            _add_drop_prerequisites(delta, delta.type_prerequisites, drops, add)
        elif isinstance(delta, AlterCompositeAttributeType):
            _add_drop_prerequisites(delta, delta.old_type_prerequisites, drops, add)
        elif isinstance(delta, DropCompositeType):
            _add_drop_prerequisites(delta, delta.composite.type_prerequisites, drops, add)
        elif isinstance(delta, DropDomain):
            _add_drop_prerequisites(delta, delta.domain.type_prerequisites, drops, add)
        elif isinstance(delta, DropConstraint):
            _add_constraint_drop_dependencies(delta, drops, add)
        elif isinstance(delta, DropIndex):
            _add_drop_prerequisites(delta, _index_refs(delta.index), drops, add)
        elif isinstance(delta, ReplaceIndex):
            _add_drop_prerequisites(delta, _index_refs(delta.old_index), drops, add)
        elif isinstance(delta, DropTable):
            sequence_prerequisites = tuple(
                ref for column in delta.table.columns for ref in column.sequence_prerequisites
            )
            _add_drop_prerequisites(
                delta,
                (*delta.table.type_prerequisites, *sequence_prerequisites),
                drops,
                add,
            )
            for constraint in delta.table.constraints:
                if isinstance(constraint, ForeignKeyConstraint):
                    _add_drop_prerequisites(delta, _fk_remote_refs(constraint), drops, add)

    _add_sequence_drop_dependencies(nodes, drops, add)


def _add_sequence_drop_dependencies(
    nodes: tuple[DeltaBase, ...],
    drops: dict[ObjectRef, list[DeltaBase]],
    add: Callable[[DeltaBase, DeltaBase], None],
) -> None:
    for delta in nodes:
        if isinstance(delta, SetColumnDefault):
            _add_drop_prerequisites(delta, delta.old_sequence_prerequisites, drops, add)
        elif isinstance(delta, AlterSequenceOwnedBy) and delta.old_owned_by is not None:
            _add_drop_prerequisites(delta, (delta.old_owned_by,), drops, add)


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
