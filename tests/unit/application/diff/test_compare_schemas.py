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
from pgschemadiff.domain.delta.schema import CreateExtension, CreateSchema
from pgschemadiff.domain.delta.table import CreateTable, RenameTable
from pgschemadiff.domain.extension import Extension
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import PartitionOf, Table


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


async def test_compare_schemas_orders_typed_deltas_by_foreign_key_dependency() -> None:
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
        parent_ref,
        child_ref,
    ]
    constraint_delta = result.deltas[3]
    assert isinstance(constraint_delta, AddConstraint)
    assert constraint_delta.target.parent == child_ref
    assert constraint_delta.constraint.name == "a_child_parent_id_fkey"
