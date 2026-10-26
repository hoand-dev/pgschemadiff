from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.column import Column
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.identity import ObjectKind, ObjectRef, QualifiedName
from pgschemadiff.domain.schema import Schema
from pgschemadiff.domain.table import Table
from pgschemadiff.domain.trigger import Trigger


def _table_ref(name: str = "items") -> ObjectRef:
    return ObjectRef(
        kind=ObjectKind.TABLE,
        qname=QualifiedName(namespace="public", name=name),
    )


def _trigger(**updates: object) -> Trigger:
    table_ref = _table_ref()
    values: dict[str, object] = {
        "ref": ObjectRef(
            kind=ObjectKind.TRIGGER,
            qname=QualifiedName(namespace="public", name="items_audit"),
            parent=table_ref,
        ),
        "table_ref": table_ref,
        "function_ref": ObjectRef(
            kind=ObjectKind.FUNCTION,
            qname=QualifiedName(namespace="public", name="audit_row"),
            arg_signature=(),
        ),
        "definition": (
            'CREATE TRIGGER "items_audit" BEFORE UPDATE OF "value" '
            'ON "public"."items" FOR EACH ROW WHEN (NEW.value > 0) '
            'EXECUTE FUNCTION "public"."audit_row"()'
        ),
        "timing": "BEFORE",
        "events": ("UPDATE",),
        "row_level": True,
        "columns": ("value",),
        "when_expr": "NEW.value > 0",
        "is_constraint": False,
        "deferrable": False,
        "initially_deferred": False,
        "enabled": "O",
    }
    values.update(updates)
    return Trigger(**values)  # type: ignore[arg-type]


def test_trigger_is_frozen_and_keeps_catalog_semantics() -> None:
    trigger = _trigger()

    assert trigger.ref.kind is ObjectKind.TRIGGER
    assert trigger.ref.parent == trigger.table_ref
    assert trigger.function_ref.arg_signature == ()
    assert trigger.events == ("UPDATE",)
    assert trigger.columns == ("value",)
    assert trigger.when_expr == "NEW.value > 0"
    with pytest.raises(ValidationError):
        trigger.enabled = "D"  # type: ignore[misc]


def test_constraint_trigger_keeps_referenced_table() -> None:
    referenced_table_ref = _table_ref("parents")

    trigger = _trigger(
        is_constraint=True,
        deferrable=True,
        referenced_table_ref=referenced_table_ref,
    )

    assert trigger.referenced_table_ref == referenced_table_ref


def test_table_and_database_aggregate_child_triggers() -> None:
    trigger = _trigger()
    table = Table(
        ref=trigger.table_ref,
        columns=(Column(name="value", position=1, data_type="integer"),),
        triggers=(trigger,),
    )
    schema_ref = ObjectRef(
        kind=ObjectKind.SCHEMA,
        qname=QualifiedName(namespace="public", name="public"),
    )
    database = Database(name="test", schemas=(Schema(ref=schema_ref, tables=(table,)),))

    assert database.all_triggers() == (trigger,)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"definition": "  "}, "definition must not be blank"),
        ({"events": ()}, "at least one event"),
        ({"events": ("INSERT", "INSERT")}, "duplicate event"),
        ({"columns": ("",)}, "column names must not be empty"),
        ({"columns": ("value", "value")}, "duplicate column"),
        ({"timing": "UNKNOWN"}, "timing"),
        ({"enabled": "X"}, "enabled"),
        ({"deferrable": True}, "non-constraint"),
        ({"is_constraint": True, "initially_deferred": True}, "deferrable"),
    ],
)
def test_trigger_rejects_invalid_catalog_state(updates: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _trigger(**updates)


def test_trigger_requires_matching_table_identity_and_function_ref() -> None:
    with pytest.raises(ValidationError, match="parent must match table_ref"):
        _trigger(table_ref=_table_ref("other"))
    with pytest.raises(ValidationError, match="FUNCTION"):
        _trigger(function_ref=_table_ref("audit_row"))


def test_table_rejects_trigger_with_unknown_update_column() -> None:
    trigger = _trigger()

    with pytest.raises(ValidationError, match="references missing column"):
        Table(ref=trigger.table_ref, triggers=(trigger,))
