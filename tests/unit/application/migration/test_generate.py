from datetime import UTC, datetime

import pytest

from pgschemadiff.application.diff.dependencies import order_deltas
from pgschemadiff.application.migration import generate_migration
from pgschemadiff.application.sql_emit.risk import RiskAssessment, RiskLevel, classify_risk
from pgschemadiff.domain.column import Column
from pgschemadiff.domain.constraint import (
    CheckConstraint,
    Constraint,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    UniqueConstraint,
)
from pgschemadiff.domain.delta import (
    AddConstraint,
    CreateIndex,
    CreateSchema,
    CreateTable,
    DeltaBase,
    DeltaSet,
    DropSchema,
    ReplaceView,
)
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.index import Index, IndexKeyColumn
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import Table
from pgschemadiff.domain.view import View
from pgschemadiff.shared.errors import MigrationError, RiskGateError


def _schema_ref(name: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name=name),
    )


def _create_schema(name: str) -> CreateSchema:
    ref = _schema_ref(name)
    return CreateSchema(target=ref, pg_schema=Schema(ref=ref))


def _drop_schema(name: str) -> DropSchema:
    ref = _schema_ref(name)
    return DropSchema(target=ref, pg_schema=Schema(ref=ref))


def _table_ref(name: str) -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name=name),
    )


def _add_constraint(table_ref: ObjectRef, constraint: Constraint) -> AddConstraint:
    target = ObjectRef(
        kind=ObjectKind.CONSTRAINT,
        qname=QualifiedName(namespace=table_ref.qname.namespace, name=constraint.name),
        parent=table_ref,
    )
    return AddConstraint(target=target, constraint=constraint)


def _clock() -> datetime:
    return datetime(2026, 10, 24, 12, 30, 45, tzinfo=UTC)


def test_generation_uses_injected_metadata_and_preserves_fingerprints() -> None:
    delta = _create_schema("app")

    plan = generate_migration(
        DeltaSet.from_iterable((delta,)),
        source_fingerprint="source-hash",
        target_fingerprint="target-hash",
        clock=_clock,
        id_factory=lambda: "fixed-plan-id",
    )

    assert plan.id == "fixed-plan-id"
    assert plan.slug == "diff"
    assert plan.created_at == _clock()
    assert plan.source_fingerprint == "source-hash"
    assert plan.target_fingerprint == "target-hash"
    assert plan.delta_set.deltas == (delta,)


def test_ordering_is_deterministic_and_bundle_ids_follow_order() -> None:
    alpha, beta = _create_schema("alpha"), _create_schema("beta")

    first = generate_migration(
        DeltaSet.from_iterable((beta, alpha)),
        clock=_clock,
        id_factory=lambda: "fixed-plan-id",
    )
    second = generate_migration(
        DeltaSet.from_iterable((alpha, beta)),
        clock=_clock,
        id_factory=lambda: "fixed-plan-id",
    )

    assert (
        first.delta_set == second.delta_set == order_deltas(DeltaSet.from_iterable((beta, alpha)))
    )
    assert tuple(item.delta_id for item in first.assessments) == ("d0001", "d0002")
    assert tuple(item.assessment.delta for item in first.assessments) == first.delta_set.deltas
    assert first == second


def test_each_ordered_delta_is_classified_once(monkeypatch: pytest.MonkeyPatch) -> None:
    alpha, beta = _create_schema("alpha"), _create_schema("beta")
    classified: list[DeltaBase] = []

    def count_classifications(
        delta: DeltaBase,
        *,
        created_tables: frozenset[ObjectRef],
    ) -> RiskAssessment:
        classified.append(delta)
        return classify_risk(delta, created_tables=created_tables)

    monkeypatch.setattr(
        "pgschemadiff.application.migration.generate.classify_risk",
        count_classifications,
    )
    plan = generate_migration(
        DeltaSet.from_iterable((beta, alpha)),
        clock=_clock,
        id_factory=lambda: "classified-once",
    )

    assert len(classified) == len(plan.delta_set)
    assert all(
        actual is expected for actual, expected in zip(classified, plan.delta_set, strict=True)
    )


def test_empty_plan_has_no_risk_or_units() -> None:
    plan = generate_migration(
        DeltaSet(),
        clock=_clock,
        id_factory=lambda: "empty-plan",
    )

    assert plan.delta_set == DeltaSet()
    assert plan.assessments == ()
    assert plan.units == ()
    assert plan.overall_max_risk is None


def test_generation_blocks_incompatible_view_replacement() -> None:
    view_ref = ObjectRef(
        kind=ObjectKind.VIEW,
        qname=QualifiedName(namespace="public", name="account_view"),
    )
    old = View(
        ref=view_ref,
        columns=(("id", "integer"),),
        definition="SELECT id FROM public.accounts",
    )
    new = View(
        ref=view_ref,
        columns=(("name", "text"),),
        definition="SELECT name FROM public.accounts",
    )
    delta = ReplaceView(target=view_ref, old_view=old, new_view=new)

    with pytest.raises(
        RiskGateError,
        match=(
            "View output column names, order, and types must remain unchanged; "
            "only append is supported"
        ),
    ):
        generate_migration(
            DeltaSet.from_iterable((delta,)),
            max_risk=RiskLevel.BLOCKED,
            clock=_clock,
            id_factory=lambda: "blocked-view-replacement",
        )


def test_new_two_table_schema_with_constraints_and_index_has_safe_max_risk() -> None:
    teams_ref = _table_ref("teams")
    users_ref = _table_ref("users")
    teams_pk = PrimaryKeyConstraint(
        name="teams_pkey", columns=("id",), definition="PRIMARY KEY (id)"
    )
    users_pk = PrimaryKeyConstraint(
        name="users_pkey", columns=("id",), definition="PRIMARY KEY (id)"
    )
    users_unique = UniqueConstraint(
        name="users_email_key", columns=("email",), definition="UNIQUE (email)"
    )
    users_check = CheckConstraint(
        name="users_email_check",
        expression="email <> ''",
        definition="CHECK (email <> '')",
    )
    users_fk = ForeignKeyConstraint(
        name="users_team_fkey",
        columns=("team_id",),
        ref_namespace="public",
        ref_table="teams",
        ref_columns=("id",),
    )
    teams = Table(
        ref=teams_ref,
        columns=(Column(name="id", position=1, data_type="integer", nullable=False),),
        constraints=(teams_pk,),
    )
    users = Table(
        ref=users_ref,
        columns=(
            Column(name="id", position=1, data_type="integer", nullable=False),
            Column(name="team_id", position=2, data_type="integer", nullable=False),
            Column(name="email", position=3, data_type="text", nullable=False),
        ),
        constraints=(users_pk, users_unique, users_check, users_fk),
    )
    index_ref = ObjectRef(
        kind=ObjectKind.INDEX,
        qname=QualifiedName(namespace="public", name="users_email_idx"),
    )
    index = Index(
        ref=index_ref,
        table_ref=users_ref,
        key_columns=(IndexKeyColumn(column_name="email"),),
        definition="CREATE INDEX users_email_idx ON public.users USING btree (email)",
    )
    delta_set = DeltaSet.from_iterable(
        (
            CreateTable(target=teams_ref, table=teams),
            CreateTable(target=users_ref, table=users),
            _add_constraint(teams_ref, teams_pk),
            _add_constraint(users_ref, users_pk),
            _add_constraint(users_ref, users_unique),
            _add_constraint(users_ref, users_check),
            _add_constraint(users_ref, users_fk),
            CreateIndex(target=index_ref, index=index),
        )
    )

    plan = generate_migration(
        delta_set,
        max_risk=RiskLevel.SAFE,
        clock=_clock,
        id_factory=lambda: "new-tables-safe",
    )

    assert plan.overall_max_risk is RiskLevel.SAFE
    assert all(record.assessment.level is RiskLevel.SAFE for record in plan.assessments)


@pytest.mark.parametrize(
    "slug",
    [("",), (".",), ("..",), ("../diff",), ("a/b",), ("a\\b",), ("UPPER",), ("a_b",), ("café",)],
)
def test_slug_rejects_non_conservative_filename_values(slug: str) -> None:
    with pytest.raises(MigrationError, match="slug"):
        generate_migration(DeltaSet(), slug=slug, clock=_clock, id_factory=lambda: "id")


def test_generation_rejects_naive_clock() -> None:
    with pytest.raises(MigrationError, match="aware"):
        generate_migration(
            DeltaSet(),
            clock=lambda: datetime(2026, 10, 24, 12),
            id_factory=lambda: "id",
        )


def test_generation_rejects_invalid_plan_id() -> None:
    with pytest.raises(MigrationError, match="id_factory"):
        generate_migration(DeltaSet(), clock=_clock, id_factory=lambda: " ")


def test_generation_rejects_non_risk_level_limit() -> None:
    with pytest.raises(MigrationError, match="max_risk"):
        generate_migration(DeltaSet(), max_risk="dangerous", clock=_clock)  # type: ignore[arg-type]


def test_risk_gate_lists_every_offending_delta_without_emitting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha, beta = _drop_schema("alpha"), _drop_schema("beta")

    class MustNotEmit:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("emitter must not be constructed for rejected plans")

    monkeypatch.setattr(
        "pgschemadiff.application.migration.generate.SqlEmitter",
        MustNotEmit,
    )

    with pytest.raises(RiskGateError) as raised:
        generate_migration(
            DeltaSet.from_iterable((beta, alpha)),
            clock=_clock,
            id_factory=lambda: "rejected-plan",
        )

    message = str(raised.value)
    ordered = order_deltas(DeltaSet.from_iterable((beta, alpha)))
    for index, delta in enumerate(ordered, start=1):
        delta_id = f"d{index:04d}"
        assert f"{delta_id} kind=drop_schema" in message
        assert f"target={delta.target.qname.fqn}" in message
        assert "level=destructive" in message
        assert "Removes a schema and its objects." in message
    assert message.index("d0001") < message.index("d0002")


def test_accepted_plan_emits_and_splits_units_with_provenance() -> None:
    delta_set = DeltaSet.from_iterable((_create_schema("alpha"), _drop_schema("omega")))

    plan = generate_migration(
        delta_set,
        max_risk=RiskLevel.DESTRUCTIVE,
        clock=_clock,
        id_factory=lambda: "accepted-plan",
    )

    assert plan.overall_max_risk is RiskLevel.DESTRUCTIVE
    assert len(plan.units) == 1
    planned_unit = plan.units[0]
    assert planned_unit.transaction_unit.transactional is True
    assert planned_unit.max_risk is RiskLevel.DESTRUCTIVE

    ids_by_delta_identity = {id(item.assessment.delta): item.delta_id for item in plan.assessments}
    expected_ids = tuple(
        dict.fromkeys(
            ids_by_delta_identity[id(statement.delta)]
            for statement in planned_unit.transaction_unit.statements
        )
    )
    assert planned_unit.delta_ids == expected_ids
    assert all(
        statement.delta
        is next(
            item.assessment.delta
            for item in plan.assessments
            if item.delta_id == ids_by_delta_identity[id(statement.delta)]
        )
        for statement in planned_unit.transaction_unit.statements
    )
