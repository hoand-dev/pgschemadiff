from pgschemadiff.application.diff.compare_schemas import compare_schemas
from pgschemadiff.application.diff.ignore import IgnoreRules
from pgschemadiff.application.diff.renames import RenameAnnotations, TableRename
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.constraint import (
    CheckConstraint,
    ForeignKeyConstraint,
    UniqueConstraint,
)
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.delta.base import DeltaSet
from pgschemadiff.domain.delta.column import AddColumn
from pgschemadiff.domain.delta.constraint import AddConstraint, DropConstraint
from pgschemadiff.domain.delta.index import CreateIndex
from pgschemadiff.domain.delta.materialized_view import CreateMaterializedView
from pgschemadiff.domain.delta.schema import CreateExtension, CreateSchema
from pgschemadiff.domain.delta.sequence import AlterSequenceOwner
from pgschemadiff.domain.delta.table import AlterTableAttrs, CreateTable, RenameTable
from pgschemadiff.domain.delta.view import CreateView
from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn
from pgschemadiff.domain.materialized_view import MaterializedView
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.sequence import Sequence
from pgschemadiff.domain.table import PartitionOf, Table
from pgschemadiff.domain.view import View


def _ref(
    kind: ObjectKind,
    name: str,
    namespace: str = "public",
) -> ObjectRef:
    return ObjectRef(
        kind=kind,
        qname=QualifiedName(namespace=namespace, name=name),
    )


def _schema() -> Schema:
    return Schema(
        ref=ObjectRef(
            kind=ObjectKind.SCHEMA,
            qname=QualifiedName(namespace="public", name="public"),
        )
    )


class StubInspector:
    def __init__(self, snapshot: Database) -> None:
        self.snapshot = snapshot
        self.calls = 0

    async def inspect(self) -> Database:
        self.calls += 1
        return self.snapshot


async def test_compare_schemas_inspects_each_database_once_and_returns_typed_schema_delta() -> None:
    source = StubInspector(Database(name="source"))
    target = StubInspector(Database(name="target", schemas=(_schema(),)))

    result = await compare_schemas(source, target)

    assert source.calls == target.calls == 1
    assert isinstance(result, DeltaSet)
    assert len(result.deltas) == 1
    assert isinstance(result.deltas[0], CreateSchema)


async def test_compare_schemas_uses_all_default_comparators() -> None:
    table_ref = _ref(ObjectKind.TABLE, "accounts")
    id_column = Column(name="id", position=1, data_type="integer", nullable=False)
    email_column = Column(name="email", position=2, data_type="text")
    source_table = Table(ref=table_ref, columns=(id_column,))
    target_table = Table(
        ref=table_ref,
        columns=(id_column, email_column),
        constraints=(UniqueConstraint(name="accounts_email_key", columns=("email",)),),
    )
    index = Index(
        ref=_ref(ObjectKind.INDEX, "accounts_email_idx"),
        table_ref=table_ref,
        key_columns=(IndexKeyColumn(column_name="email"),),
    )
    extension = Extension(ref=_ref(ObjectKind.EXTENSION, "pgcrypto"), version="1.3")
    source = StubInspector(
        Database(name="source", schemas=(Schema(ref=_schema().ref, tables=(source_table,)),))
    )
    target = StubInspector(
        Database(
            name="target",
            schemas=(Schema(ref=_schema().ref, tables=(target_table,), indexes=(index,)),),
            extensions=(extension,),
        )
    )

    result = await compare_schemas(source, target)

    delta_types = {type(delta) for delta in result.deltas}
    assert {AddColumn, AddConstraint, CreateIndex, CreateExtension} <= delta_types


async def test_compare_schemas_includes_view_comparator() -> None:
    view_ref = _ref(ObjectKind.VIEW, "active_accounts")
    view = View(
        ref=view_ref,
        columns=(("id", "integer"),),
        definition="SELECT id FROM public.accounts",
    )
    target = StubInspector(
        Database(name="target", schemas=(Schema(ref=_schema().ref, views=(view,)),))
    )

    result = await compare_schemas(StubInspector(Database(name="source")), target)

    assert CreateView(target=view_ref, view=view) in result.deltas


async def test_compare_schemas_includes_materialized_view_comparator() -> None:
    materialized_view = MaterializedView(
        ref=_ref(ObjectKind.MATERIALIZED_VIEW, "account_totals"),
        columns=(("id", "integer"),),
        definition="SELECT id FROM public.accounts",
    )
    target = StubInspector(
        Database(
            name="target",
            schemas=(Schema(ref=_schema().ref, materialized_views=(materialized_view,)),),
        )
    )

    result = await compare_schemas(StubInspector(Database(name="source")), target)

    assert (
        CreateMaterializedView(
            target=materialized_view.ref,
            materialized_view=materialized_view,
        )
        in result.deltas
    )


async def test_compare_schemas_includes_sequence_comparator() -> None:
    sequence = Sequence(
        ref=_ref(ObjectKind.SEQUENCE, "ticket_seq"),
        data_type="bigint",
        start=1,
        increment=1,
        min_value=1,
        max_value=999,
        cache=1,
        cycle=False,
        owner="app_owner",
    )
    target = StubInspector(
        Database(name="target", schemas=(Schema(ref=_schema().ref, sequences=(sequence,)),))
    )

    result = await compare_schemas(StubInspector(Database(name="source")), target)

    assert any(delta.target == sequence.ref for delta in result.deltas)


async def test_compare_schemas_uses_table_owner_change_for_linked_sequence() -> None:
    table_ref = _ref(ObjectKind.TABLE, "tickets")
    column_ref = ObjectRef(
        kind=ObjectKind.COLUMN,
        qname=QualifiedName(namespace="public", name="id"),
        parent=table_ref,
    )
    source_sequence = Sequence(
        ref=_ref(ObjectKind.SEQUENCE, "ticket_seq"),
        data_type="bigint",
        start=1,
        increment=1,
        min_value=1,
        max_value=999,
        cache=1,
        cycle=False,
        owner="old_owner",
        owned_by=column_ref,
    )
    target_sequence = source_sequence.model_copy(update={"owner": "new_owner"})
    source_table = Table(
        ref=table_ref,
        columns=(Column(name="id", position=1, data_type="bigint"),),
        owner="old_owner",
    )
    target_table = source_table.model_copy(update={"owner": "new_owner"})
    source = StubInspector(
        Database(
            name="source",
            schemas=(
                Schema(
                    ref=_schema().ref,
                    tables=(source_table,),
                    sequences=(source_sequence,),
                ),
            ),
        )
    )
    target = StubInspector(
        Database(
            name="target",
            schemas=(
                Schema(
                    ref=_schema().ref,
                    tables=(target_table,),
                    sequences=(target_sequence,),
                ),
            ),
        )
    )

    result = await compare_schemas(source, target)

    assert any(isinstance(delta, AlterTableAttrs) for delta in result.deltas)
    assert not any(isinstance(delta, AlterSequenceOwner) for delta in result.deltas)


async def test_compare_schemas_creates_table_before_local_constraints() -> None:
    table_ref = _ref(ObjectKind.TABLE, "accounts")
    column = Column(name="id", position=1, data_type="integer", nullable=False)
    table = Table(
        ref=table_ref,
        columns=(column,),
        constraints=(
            CheckConstraint(name="z_local_check", expression="id < 100"),
            CheckConstraint(name="parent_check", expression="id > 0", inherited=True),
            CheckConstraint(name="a_local_check", expression="id >= 0"),
        ),
    )
    target = StubInspector(
        Database(name="target", schemas=(Schema(ref=_schema().ref, tables=(table,)),))
    )

    result = await compare_schemas(StubInspector(Database(name="source")), target)

    assert [type(delta) for delta in result.deltas] == [
        CreateSchema,
        CreateTable,
        AddConstraint,
        AddConstraint,
    ]
    create_table = result.deltas[1]
    assert isinstance(create_table, CreateTable)
    assert create_table.table == table
    additions = [delta for delta in result.deltas if isinstance(delta, AddConstraint)]
    assert [delta.constraint.name for delta in additions] == ["a_local_check", "z_local_check"]
    assert all(delta.target.parent == table.ref for delta in additions)
    assert not any(isinstance(delta, AddColumn) for delta in result.deltas)


async def test_compare_schemas_ignores_changed_inherited_partition_constraints() -> None:
    parent_ref = _ref(ObjectKind.TABLE, "parents")
    child_ref = _ref(ObjectKind.TABLE, "children")
    parent = Table(ref=parent_ref)
    inherited_source = CheckConstraint(name="parent_check", expression="id > 0", inherited=True)
    inherited_target = CheckConstraint(name="parent_check", expression="id >= 0", inherited=True)
    child_source = Table(
        ref=child_ref,
        constraints=(
            inherited_source,
            CheckConstraint(name="local_old", expression="value > 0"),
        ),
        partition_of=PartitionOf(parent_namespace="public", parent_name="parents"),
    )
    child_target = Table(
        ref=child_ref,
        constraints=(
            inherited_target,
            CheckConstraint(name="local_new", expression="value >= 0"),
        ),
        partition_of=PartitionOf(parent_namespace="public", parent_name="parents"),
    )
    source = StubInspector(
        Database(
            name="source",
            schemas=(Schema(ref=_schema().ref, tables=(parent, child_source)),),
        )
    )
    target = StubInspector(
        Database(
            name="target",
            schemas=(Schema(ref=_schema().ref, tables=(parent, child_target)),),
        )
    )

    result = await compare_schemas(source, target)

    assert len(result.deltas) == 2
    constraint_deltas = [
        delta for delta in result.deltas if isinstance(delta, (DropConstraint, AddConstraint))
    ]
    assert {type(delta) for delta in constraint_deltas} == {DropConstraint, AddConstraint}
    assert {delta.constraint.name for delta in constraint_deltas} == {"local_old", "local_new"}


async def test_compare_schemas_applies_programmatic_ignore_rules() -> None:
    extension_ref = _ref(ObjectKind.EXTENSION, "pgcrypto")
    source = StubInspector(Database(name="source"))
    target = StubInspector(
        Database(
            name="target",
            extensions=(Extension(ref=extension_ref, version="1.3"),),
        )
    )

    result = await compare_schemas(
        source,
        target,
        ignore=IgnoreRules(objects=frozenset({extension_ref})),
    )

    assert result.deltas == ()


async def test_compare_schemas_forwards_rename_annotations() -> None:
    source_name = QualifiedName(namespace="public", name="old_accounts")
    target_name = QualifiedName(namespace="public", name="accounts")
    column = Column(name="id", position=1, data_type="integer", nullable=False)
    source_schema = Schema(
        ref=_schema().ref,
        tables=(Table(ref=_ref(ObjectKind.TABLE, "old_accounts"), columns=(column,)),),
    )
    target_schema = Schema(
        ref=_schema().ref,
        tables=(Table(ref=_ref(ObjectKind.TABLE, "accounts"), columns=(column,)),),
    )
    source = StubInspector(Database(name="source", schemas=(source_schema,)))
    target = StubInspector(Database(name="target", schemas=(target_schema,)))
    renames = RenameAnnotations(tables=(TableRename(source=source_name, target=target_name),))

    result = await compare_schemas(source, target, renames=renames)

    assert len(result.deltas) == 1
    assert isinstance(result.deltas[0], RenameTable)


async def test_compare_schemas_creates_fk_tables_before_separate_constraint() -> None:
    parent_ref = _ref(ObjectKind.TABLE, "z_parent")
    child_ref = _ref(ObjectKind.TABLE, "a_child")
    parent = Table(
        ref=parent_ref,
        columns=(Column(name="id", position=1, data_type="integer", nullable=False),),
    )
    child = Table(
        ref=child_ref,
        columns=(Column(name="parent_id", position=1, data_type="integer", nullable=False),),
        constraints=(
            ForeignKeyConstraint(
                name="a_child_parent_id_fkey",
                columns=("parent_id",),
                ref_namespace="public",
                ref_table="z_parent",
                ref_columns=("id",),
            ),
        ),
    )
    target = StubInspector(
        Database(
            name="target",
            schemas=(Schema(ref=_schema().ref, tables=(child, parent)),),
        )
    )

    result = await compare_schemas(StubInspector(Database(name="source")), target)

    assert isinstance(result, DeltaSet)
    assert [type(delta) for delta in result.deltas] == [
        CreateSchema,
        CreateTable,
        CreateTable,
        AddConstraint,
    ]
    assert [delta.target for delta in result.deltas[:3]] == [
        _schema().ref,
        child_ref,
        parent_ref,
    ]
    constraint_delta = result.deltas[3]
    assert isinstance(constraint_delta, AddConstraint)
    assert constraint_delta.target.parent == child_ref
    assert constraint_delta.constraint.name == "a_child_parent_id_fkey"
