"""Unit tests for ``pgschemadiff.domain.column`` (task P1-DOM-02)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.column import Column, GeneratedTiming, IdentitySpec

# ---------------------------------------------------------------------------
# GeneratedTiming
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_generated_timing_is_str_enum() -> None:
    assert isinstance(GeneratedTiming.ALWAYS, str)
    assert GeneratedTiming.ALWAYS == "always"
    assert GeneratedTiming.BY_DEFAULT == "by_default"


@pytest.mark.unit
def test_generated_timing_round_trips() -> None:
    for v in GeneratedTiming:
        assert GeneratedTiming(str(v)) is v


# ---------------------------------------------------------------------------
# IdentitySpec
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_identity_spec_minimal() -> None:
    spec = IdentitySpec(generated=GeneratedTiming.ALWAYS)
    assert spec.generated is GeneratedTiming.ALWAYS
    assert spec.sequence_start is None
    assert spec.sequence_increment is None
    assert spec.sequence_min_value is None
    assert spec.sequence_max_value is None
    assert spec.sequence_cache is None
    assert spec.sequence_cycle is False


@pytest.mark.unit
def test_identity_spec_by_default() -> None:
    spec = IdentitySpec(generated=GeneratedTiming.BY_DEFAULT)
    assert spec.generated is GeneratedTiming.BY_DEFAULT


@pytest.mark.unit
def test_identity_spec_full_options() -> None:
    spec = IdentitySpec(
        generated=GeneratedTiming.ALWAYS,
        sequence_start=1,
        sequence_increment=1,
        sequence_min_value=1,
        sequence_max_value=9999,
        sequence_cache=1,
        sequence_cycle=True,
    )
    assert spec.sequence_max_value == 9999
    assert spec.sequence_cycle is True


@pytest.mark.unit
def test_identity_spec_min_max_validation_ok() -> None:
    spec = IdentitySpec(
        generated=GeneratedTiming.ALWAYS,
        sequence_min_value=1,
        sequence_max_value=100,
    )
    assert spec.sequence_min_value == 1
    assert spec.sequence_max_value == 100


@pytest.mark.unit
def test_identity_spec_min_greater_than_max_rejected() -> None:
    with pytest.raises(ValidationError, match="must not exceed"):
        IdentitySpec(
            generated=GeneratedTiming.ALWAYS,
            sequence_min_value=100,
            sequence_max_value=1,
        )


@pytest.mark.unit
def test_identity_spec_min_equal_max_ok() -> None:
    spec = IdentitySpec(
        generated=GeneratedTiming.ALWAYS,
        sequence_min_value=42,
        sequence_max_value=42,
    )
    assert spec.sequence_min_value == spec.sequence_max_value


@pytest.mark.unit
def test_identity_spec_is_frozen() -> None:
    spec = IdentitySpec(generated=GeneratedTiming.ALWAYS)
    with pytest.raises(ValidationError):
        spec.generated = GeneratedTiming.BY_DEFAULT  # type: ignore[misc]


@pytest.mark.unit
def test_identity_spec_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        IdentitySpec(generated=GeneratedTiming.ALWAYS, bogus=1)  # type: ignore[call-arg]


@pytest.mark.unit
def test_identity_spec_json_round_trip() -> None:
    spec = IdentitySpec(
        generated=GeneratedTiming.BY_DEFAULT,
        sequence_start=100,
        sequence_cycle=True,
    )
    restored = IdentitySpec.model_validate_json(spec.model_dump_json())
    assert restored == spec


# ---------------------------------------------------------------------------
# Column — plain column
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_plain_column_minimal() -> None:
    col = Column(name="id", position=1, data_type="integer")
    assert col.name == "id"
    assert col.position == 1
    assert col.data_type == "integer"
    assert col.nullable is True
    assert col.default_expr is None
    assert col.collation is None
    assert col.identity is None
    assert col.generated_expression is None


@pytest.mark.unit
def test_plain_column_not_null() -> None:
    col = Column(name="email", position=2, data_type="text", nullable=False)
    assert col.nullable is False


@pytest.mark.unit
def test_plain_column_with_default() -> None:
    col = Column(
        name="created_at",
        position=3,
        data_type="timestamptz",
        default_expr="now()",
    )
    assert col.default_expr == "now()"


@pytest.mark.unit
def test_plain_column_with_collation() -> None:
    col = Column(
        name="label",
        position=1,
        data_type="text",
        collation="en_US.utf8",
    )
    assert col.collation == "en_US.utf8"


@pytest.mark.unit
def test_column_position_must_be_ge1() -> None:
    with pytest.raises(ValidationError):
        Column(name="id", position=0, data_type="integer")


@pytest.mark.unit
def test_column_name_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        Column(name="", position=1, data_type="integer")


@pytest.mark.unit
def test_column_data_type_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        Column(name="id", position=1, data_type="")


@pytest.mark.unit
def test_column_is_frozen() -> None:
    col = Column(name="id", position=1, data_type="integer")
    with pytest.raises(ValidationError):
        col.name = "x"  # type: ignore[misc]


@pytest.mark.unit
def test_column_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Column(name="id", position=1, data_type="integer", unknown_field=1)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Column — identity column
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_identity_column_ok() -> None:
    spec = IdentitySpec(generated=GeneratedTiming.ALWAYS)
    col = Column(name="id", position=1, data_type="bigint", nullable=False, identity=spec)
    assert col.is_identity is True
    assert col.is_generated_stored is False
    assert col.identity is spec


@pytest.mark.unit
def test_identity_column_no_default_expr() -> None:
    spec = IdentitySpec(generated=GeneratedTiming.ALWAYS)
    with pytest.raises(ValidationError, match="must not have a default_expr"):
        Column(
            name="id",
            position=1,
            data_type="bigint",
            identity=spec,
            default_expr="42",
        )


# ---------------------------------------------------------------------------
# Column — generated stored column
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_generated_stored_column_ok() -> None:
    col = Column(
        name="full_name",
        position=3,
        data_type="text",
        nullable=False,
        generated_expression="(first_name || ' ' || last_name)",
    )
    assert col.is_generated_stored is True
    assert col.is_identity is False


@pytest.mark.unit
def test_generated_stored_no_default_expr() -> None:
    with pytest.raises(ValidationError, match="must not have a default_expr"):
        Column(
            name="full_name",
            position=3,
            data_type="text",
            generated_expression="(first_name || ' ' || last_name)",
            default_expr="''",
        )


@pytest.mark.unit
def test_cannot_be_both_identity_and_generated() -> None:
    spec = IdentitySpec(generated=GeneratedTiming.ALWAYS)
    with pytest.raises(ValidationError, match="cannot be both"):
        Column(
            name="id",
            position=1,
            data_type="bigint",
            identity=spec,
            generated_expression="42",
        )


# ---------------------------------------------------------------------------
# Column — properties
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_is_identity_false_for_plain_column() -> None:
    col = Column(name="x", position=1, data_type="text")
    assert col.is_identity is False


@pytest.mark.unit
def test_is_generated_stored_false_for_plain_column() -> None:
    col = Column(name="x", position=1, data_type="text")
    assert col.is_generated_stored is False


# ---------------------------------------------------------------------------
# Column — JSON round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_column_json_round_trip_plain() -> None:
    col = Column(
        name="email",
        position=2,
        data_type="text",
        nullable=False,
        default_expr="''",
        collation="en_US.utf8",
    )
    restored = Column.model_validate_json(col.model_dump_json())
    assert restored == col


@pytest.mark.unit
def test_column_json_round_trip_identity() -> None:
    spec = IdentitySpec(
        generated=GeneratedTiming.BY_DEFAULT,
        sequence_start=1000,
        sequence_increment=5,
    )
    col = Column(name="id", position=1, data_type="bigint", nullable=False, identity=spec)
    restored = Column.model_validate_json(col.model_dump_json())
    assert restored == col
    assert restored.identity == spec


@pytest.mark.unit
def test_column_equality_and_hash() -> None:
    a = Column(name="id", position=1, data_type="integer")
    b = Column(name="id", position=1, data_type="integer")
    c = Column(name="id", position=2, data_type="integer")
    assert a == b
    assert hash(a) == hash(b)
    assert a != c
