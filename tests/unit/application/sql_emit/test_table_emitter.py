from collections.abc import Iterable

import pytest
from syrupy.assertion import SnapshotAssertion

from pgschemadiff.application.sql_emit.emitter import SqlStatement
from pgschemadiff.application.sql_emit.table_emitter import handlers
from pgschemadiff.domain.column import Column, GeneratedTiming, IdentitySpec
from pgschemadiff.domain.constraint import CheckConstraint
from pgschemadiff.domain.delta.base import DeltaBase
from pgschemadiff.domain.delta.table import AlterTableAttrs, CreateTable, DropTable, RenameTable
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.table import PartitionInfo, PartitionOf, PartitionStrategy, Table
from pgschemadiff.shared.errors import MigrationError


def _table_ref(namespace: str = "Sales", name: str = 'Order"Items') -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace=namespace, name=name),
    )


def _table(
    *,
    ref: ObjectRef | None = None,
    columns: tuple[Column, ...] = (),
    constraints: tuple[CheckConstraint, ...] = (),
    owner: str | None = None,
    tablespace: str | None = None,
    partition_info: PartitionInfo | None = None,
    partition_of: PartitionOf | None = None,
    comment: str | None = None,
    unlogged: bool = False,
    row_security: bool = False,
    force_row_security: bool = False,
) -> Table:
    return Table(
        ref=ref or _table_ref(),
        columns=columns,
        constraints=constraints,
        owner=owner,
        tablespace=tablespace,
        partition_info=partition_info,
        partition_of=partition_of,
        comment=comment,
        unlogged=unlogged,
        row_security=row_security,
        force_row_security=force_row_security,
    )


def _assert_emitted(
    statements: Iterable[SqlStatement], delta: DeltaBase, count: int
) -> tuple[SqlStatement, ...]:
    result = tuple(statements)
    assert len(result) == count
    assert all(statement.transactional is True for statement in result)
    assert all(statement.delta is delta for statement in result)
    return result


def test_handlers_cover_exact_table_delta_types() -> None:
    assert set(handlers()) == {CreateTable, DropTable, RenameTable, AlterTableAttrs}


def test_create_table_sorts_columns_ignores_constraints_and_emits_followups(
    snapshot: SnapshotAssertion,
) -> None:
    ref = _table_ref()
    columns = (
        Column(
            name='say"what',
            position=4,
            data_type="text",
            default_expr="'it''s ready'::text",
        ),
        Column(
            name="total",
            position=3,
            data_type="integer",
            nullable=False,
            generated_expression="price * qty",
        ),
        Column(
            name="select",
            position=2,
            data_type="integer",
            nullable=False,
            identity=IdentitySpec(
                generated=GeneratedTiming.BY_DEFAULT,
                sequence_start=5,
                sequence_increment=2,
                sequence_min_value=1,
                sequence_max_value=999,
                sequence_cache=8,
                sequence_cycle=True,
            ),
        ),
        Column(
            name="Created At",
            position=1,
            data_type="text",
            nullable=False,
            collation='"C"',
        ),
    )
    table = _table(
        ref=ref,
        columns=columns,
        constraints=(CheckConstraint(name="positive_total", expression="total > 0"),),
        owner='Role"Owner',
        tablespace="fast space",
        comment="Customer's order",
    )
    delta = CreateTable(target=ref, table=table)

    statements = _assert_emitted(handlers()[CreateTable](delta), delta, 4)

    assert tuple(statement.sql for statement in statements) == snapshot


@pytest.mark.unit
def test_create_unlogged_table_uses_unlogged_keyword() -> None:
    ref = _table_ref()
    table = _table(
        ref=ref,
        columns=(Column(name="id", position=1, data_type="integer"),),
        unlogged=True,
    )
    delta = CreateTable(target=ref, table=table)

    statements = _assert_emitted(handlers()[CreateTable](delta), delta, 1)

    assert tuple(statement.sql for statement in statements) == (
        'CREATE UNLOGGED TABLE "Sales"."Order""Items" ("id" integer)',
    )


def test_create_table_emits_row_security_flags() -> None:
    ref = _table_ref()
    table = _table(
        ref=ref,
        columns=(Column(name="id", position=1, data_type="integer"),),
        row_security=True,
        force_row_security=True,
    )
    delta = CreateTable(target=ref, table=table)

    statements = _assert_emitted(handlers()[CreateTable](delta), delta, 3)

    assert tuple(statement.sql for statement in statements) == (
        'CREATE TABLE "Sales"."Order""Items" ("id" integer)',
        'ALTER TABLE "Sales"."Order""Items" ENABLE ROW LEVEL SECURITY',
        'ALTER TABLE "Sales"."Order""Items" FORCE ROW LEVEL SECURITY',
    )


def test_alter_table_attrs_emits_rls_disable_and_no_force() -> None:
    delta = AlterTableAttrs(
        target=_table_ref(),
        new_row_security=False,
        new_force_row_security=False,
    )

    statements = _assert_emitted(handlers()[AlterTableAttrs](delta), delta, 2)

    assert tuple(statement.sql for statement in statements) == (
        'ALTER TABLE "Sales"."Order""Items" DISABLE ROW LEVEL SECURITY',
        'ALTER TABLE "Sales"."Order""Items" NO FORCE ROW LEVEL SECURITY',
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("unlogged", "sql_action"),
    [(True, "UNLOGGED"), (False, "LOGGED")],
    ids=["set-unlogged", "set-logged"],
)
def test_alter_table_attrs_changes_persistence(unlogged: bool, sql_action: str) -> None:
    delta = AlterTableAttrs(target=_table_ref(), new_unlogged=unlogged)

    statements = _assert_emitted(handlers()[AlterTableAttrs](delta), delta, 1)

    assert tuple(statement.sql for statement in statements) == (
        f'ALTER TABLE "Sales"."Order""Items" SET {sql_action}',
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("partition_info", "partition_of"),
    [
        pytest.param(
            PartitionInfo(strategy=PartitionStrategy.RANGE, partition_key="RANGE (id)"),
            None,
            id="partition-root",
        ),
        pytest.param(
            None,
            PartitionOf(parent_namespace="Sales", parent_name="events"),
            id="partition-child",
        ),
    ],
)
def test_create_unlogged_partition_table_fails_closed(
    partition_info: PartitionInfo | None,
    partition_of: PartitionOf | None,
) -> None:
    ref = _table_ref()
    table = _table(
        ref=ref,
        partition_info=partition_info,
        partition_of=partition_of,
        unlogged=True,
    )
    delta = CreateTable(target=ref, table=table)

    with pytest.raises(
        MigrationError,
        match="UNLOGGED tables with partition metadata are unsupported by PostgreSQL 18",
    ):
        handlers()[CreateTable](delta)


def test_create_partition_root_uses_full_pg_get_partkeydef_clause(
    snapshot: SnapshotAssertion,
) -> None:
    ref = _table_ref(name="events")
    table = _table(
        ref=ref,
        columns=(Column(name="created_at", position=1, data_type="date"),),
        partition_info=PartitionInfo(
            strategy=PartitionStrategy.RANGE,
            partition_key="RANGE (created_at)",
        ),
    )
    delta = CreateTable(target=ref, table=table)

    statements = _assert_emitted(handlers()[CreateTable](delta), delta, 1)

    assert tuple(statement.sql for statement in statements) == snapshot


def test_create_partition_child_uses_catalog_bound_without_repeating_keyword(
    snapshot: SnapshotAssertion,
) -> None:
    ref = _table_ref(name="events_2026")
    table = _table(
        ref=ref,
        columns=(Column(name="not_emitted", position=1, data_type="integer"),),
        partition_of=PartitionOf(
            parent_namespace="Sales",
            parent_name="events",
            partition_bound="FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')",
        ),
    )
    delta = CreateTable(target=ref, table=table)

    statements = _assert_emitted(handlers()[CreateTable](delta), delta, 1)

    assert tuple(statement.sql for statement in statements) == snapshot


def test_create_subpartition_child_emits_partition_bound_and_key(
    snapshot: SnapshotAssertion,
) -> None:
    ref = _table_ref(name="events_2026_q1")
    table = Table.model_construct(
        ref=ref,
        partition_of=PartitionOf(
            parent_namespace="Sales",
            parent_name="events_2026",
            partition_bound="FOR VALUES FROM ('2026-01-01') TO ('2026-04-01')",
        ),
        partition_info=PartitionInfo(
            strategy=PartitionStrategy.RANGE,
            partition_key="RANGE (created_at)",
        ),
    )
    delta = CreateTable.model_construct(target=ref, table=table)

    statements = _assert_emitted(handlers()[CreateTable](delta), delta, 1)

    assert tuple(statement.sql for statement in statements) == (
        'CREATE TABLE "Sales"."events_2026_q1" PARTITION OF "Sales"."events_2026" '
        "FOR VALUES FROM ('2026-01-01') TO ('2026-04-01') PARTITION BY RANGE (created_at)",
    )
    assert tuple(statement.sql for statement in statements) == snapshot


def test_create_default_partition_uses_default_bound(snapshot: SnapshotAssertion) -> None:
    ref = _table_ref(name="events_default")
    table = _table(
        ref=ref,
        partition_of=PartitionOf(parent_namespace="Sales", parent_name="events"),
    )
    delta = CreateTable(target=ref, table=table)

    statements = _assert_emitted(handlers()[CreateTable](delta), delta, 1)

    assert tuple(statement.sql for statement in statements) == snapshot


def test_drop_table_is_restrict(snapshot: SnapshotAssertion) -> None:
    ref = _table_ref()
    delta = DropTable(target=ref, table=_table(ref=ref))

    statements = _assert_emitted(handlers()[DropTable](delta), delta, 1)

    assert tuple(statement.sql for statement in statements) == snapshot


def test_rename_table_changes_schema_after_renaming(snapshot: SnapshotAssertion) -> None:
    old_name = QualifiedName(namespace='Old "Schema', name="old")
    new_name = QualifiedName(namespace="New Schema", name='New"Name')
    delta = RenameTable(
        target=ObjectRef(kind=ObjectKind.TABLE, qname=old_name),
        old_name=old_name,
        new_name=new_name,
    )

    statements = _assert_emitted(handlers()[RenameTable](delta), delta, 2)

    assert tuple(statement.sql for statement in statements) == snapshot


def test_rename_table_same_schema_emits_one_statement(snapshot: SnapshotAssertion) -> None:
    old_name = QualifiedName(namespace="Sales", name="old")
    new_name = QualifiedName(namespace="Sales", name="new")
    delta = RenameTable(
        target=ObjectRef(kind=ObjectKind.TABLE, qname=old_name),
        old_name=old_name,
        new_name=new_name,
    )

    statements = _assert_emitted(handlers()[RenameTable](delta), delta, 1)

    assert tuple(statement.sql for statement in statements) == snapshot


def test_alter_table_attrs_emits_supported_fields_and_clears_comment(
    snapshot: SnapshotAssertion,
) -> None:
    delta = AlterTableAttrs(
        target=_table_ref(),
        new_owner="new_owner",
        new_tablespace="archive",
        new_comment="",
    )

    statements = _assert_emitted(handlers()[AlterTableAttrs](delta), delta, 3)

    assert tuple(statement.sql for statement in statements) == snapshot


def test_alter_table_attrs_rejects_partition_changes() -> None:
    deltas = (
        AlterTableAttrs(
            target=_table_ref(),
            new_partition_info=PartitionInfo(
                strategy=PartitionStrategy.RANGE,
                partition_key="RANGE (id)",
            ),
        ),
        AlterTableAttrs(
            target=_table_ref(),
            new_partition_of=PartitionOf(parent_namespace="Sales", parent_name="parent"),
        ),
    )

    for delta in deltas:
        with pytest.raises(MigrationError):
            handlers()[AlterTableAttrs](delta)


def test_alter_table_attrs_rejects_partial_supported_output_with_partition_change() -> None:
    delta = AlterTableAttrs.model_construct(
        target=_table_ref(),
        new_owner="owner",
        new_partition_info=PartitionInfo(
            strategy=PartitionStrategy.RANGE,
            partition_key="RANGE (id)",
        ),
    )

    with pytest.raises(MigrationError):
        handlers()[AlterTableAttrs](delta)


def test_alter_table_attrs_rejects_no_supported_fields() -> None:
    delta = AlterTableAttrs.model_construct(target=_table_ref())

    with pytest.raises(MigrationError):
        handlers()[AlterTableAttrs](delta)


@pytest.mark.parametrize(
    ("delta_type", "delta"),
    [
        (CreateTable, DropTable(target=_table_ref(), table=_table())),
        (DropTable, CreateTable(target=_table_ref(), table=_table())),
        (
            RenameTable,
            CreateTable(target=_table_ref(), table=_table()),
        ),
        (
            AlterTableAttrs,
            CreateTable(target=_table_ref(), table=_table()),
        ),
    ],
)
def test_table_handlers_reject_wrong_delta_types(
    delta_type: type[DeltaBase], delta: DeltaBase
) -> None:
    with pytest.raises(MigrationError):
        handlers()[delta_type](delta)


@pytest.mark.parametrize("partition_key", ["?", "  "], ids=["sentinel", "blank"])
def test_create_table_rejects_partition_key_placeholder(partition_key: str) -> None:
    ref = _table_ref()
    table = _table(
        ref=ref,
        partition_info=PartitionInfo(
            strategy=PartitionStrategy.RANGE,
            partition_key=partition_key,
        ),
    )
    delta = CreateTable(target=ref, table=table)

    with pytest.raises(MigrationError):
        handlers()[CreateTable](delta)


@pytest.mark.parametrize("partition_bound", ["?", "  "], ids=["sentinel", "blank"])
def test_create_table_rejects_partition_bound_placeholder(partition_bound: str) -> None:
    ref = _table_ref()
    table = _table(
        ref=ref,
        partition_of=PartitionOf(
            parent_namespace="Sales",
            parent_name="events",
            partition_bound=partition_bound,
        ),
    )
    delta = CreateTable(target=ref, table=table)

    with pytest.raises(MigrationError):
        handlers()[CreateTable](delta)


def test_create_table_rejects_invalid_identifier() -> None:
    ref = _table_ref(name="bad\x00name")
    delta = CreateTable(target=ref, table=_table(ref=ref))

    with pytest.raises(MigrationError):
        handlers()[CreateTable](delta)


def test_create_table_rejects_comment_with_nul() -> None:
    ref = _table_ref()
    delta = CreateTable(
        target=ref,
        table=_table(ref=ref, comment="bad\x00comment"),
    )

    with pytest.raises(MigrationError):
        handlers()[CreateTable](delta)
