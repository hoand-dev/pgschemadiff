"""Unit tests for ``pgschemadiff.infrastructure.postgres.type_normalizer``
(task P1-INFRA-06).

These tests do NOT require a live PostgreSQL instance.  They verify:

- Alias canonicalization for all entries in the alias map.
- Type modifier (precision/scale) preservation.
- Array suffix preservation (``[]``, leading underscore ``_typename`` form).
- Identity cases: already-canonical strings pass through unchanged.
- Quoted ``"char"`` is returned as-is (Postgres internal single-byte type).
- Unknown/user-defined type names are passed through unchanged.
- Whitespace edge cases are handled gracefully.
"""

from __future__ import annotations

import pytest

from pgschemadiff.infrastructure.postgres.type_normalizer import normalize_type

# ===========================================================================
# Alias map tests
# ===========================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # ── Integer aliases ─────────────────────────────────────────────────
        ("int2", "smallint"),
        ("smallint", "smallint"),  # identity
        ("int4", "integer"),
        ("int", "integer"),
        ("integer", "integer"),  # identity
        ("int8", "bigint"),
        ("bigint", "bigint"),  # identity
        # ── Floating-point aliases ──────────────────────────────────────────
        ("float4", "real"),
        ("real", "real"),  # identity
        ("float8", "double precision"),
        ("double precision", "double precision"),  # identity (two-word)
        # ── Boolean ─────────────────────────────────────────────────────────
        ("bool", "boolean"),
        ("boolean", "boolean"),  # identity
        # ── Character types ─────────────────────────────────────────────────
        ("bpchar", "character"),
        ("character", "character"),  # identity
        ("char", "character"),
        ("varchar", "character varying"),
        ("character varying", "character varying"),  # identity
        # ── Numeric / decimal ───────────────────────────────────────────────
        ("decimal", "numeric"),
        ("numeric", "numeric"),  # identity
        # ── Date/time ───────────────────────────────────────────────────────
        ("timetz", "time with time zone"),
        ("time with time zone", "time with time zone"),  # identity
        ("time without time zone", "time without time zone"),  # identity
        ("timestamptz", "timestamp with time zone"),
        ("timestamp with time zone", "timestamp with time zone"),  # identity
        ("timestamp without time zone", "timestamp without time zone"),  # identity
        # ── Pass-through identities ─────────────────────────────────────────
        ("text", "text"),
        ("bytea", "bytea"),
        ("uuid", "uuid"),
        ("json", "json"),
        ("jsonb", "jsonb"),
        ("date", "date"),
        ("interval", "interval"),
        ("money", "money"),
        ("oid", "oid"),
        ("name", "name"),
        ("inet", "inet"),
        ("cidr", "cidr"),
        ("xml", "xml"),
        ("tsvector", "tsvector"),
        ("tsquery", "tsquery"),
    ],
)
def test_alias_canonicalization(raw: str, expected: str) -> None:
    """Each alias must map to its canonical SQL name."""
    assert normalize_type(raw) == expected


# ===========================================================================
# Modifier (precision/scale) preservation
# ===========================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # varchar(n) → character varying(n)
        ("character varying(255)", "character varying(255)"),
        ("varchar(100)", "character varying(100)"),
        # bpchar(n) → character(n)
        ("bpchar(10)", "character(10)"),
        ("character(1)", "character(1)"),
        # numeric(p,s) / decimal(p,s)
        ("numeric(10,2)", "numeric(10,2)"),
        ("decimal(8,3)", "numeric(8,3)"),
        ("numeric(18,6)", "numeric(18,6)"),
        # integer / bigint with no modifier — must NOT gain one
        ("int4", "integer"),
        ("int8", "bigint"),
        # timestamp with precision
        ("timestamp without time zone", "timestamp without time zone"),
        ("timestamp(6) without time zone", "timestamp(6) without time zone"),
        ("timestamp(3) with time zone", "timestamp(3) with time zone"),
        # time with precision
        ("time(3) without time zone", "time(3) without time zone"),
        ("time(6) with time zone", "time(6) with time zone"),
        # bit(n)
        ("bit(8)", "bit(8)"),
        ("bit varying(64)", "bit varying(64)"),
        # interval precision/fields
        ("interval(6)", "interval(6)"),
    ],
)
def test_modifier_preservation(raw: str, expected: str) -> None:
    """Type modifiers (precision, scale) must be preserved verbatim."""
    assert normalize_type(raw) == expected


# ===========================================================================
# Array suffix handling
# ===========================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Standard [] suffix
        ("integer[]", "integer[]"),
        ("text[]", "text[]"),
        ("boolean[]", "boolean[]"),
        ("numeric(10,2)[]", "numeric(10,2)[]"),
        ("character varying(255)[]", "character varying(255)[]"),
        # Alias + [] suffix
        ("int4[]", "integer[]"),
        ("bool[]", "boolean[]"),
        ("float8[]", "double precision[]"),
        ("varchar[]", "character varying[]"),
        ("bpchar[]", "character[]"),
        ("decimal[]", "numeric[]"),
        # Leading-underscore form (pg_catalog internal representation)
        ("_int4", "integer[]"),
        ("_text", "text[]"),
        ("_bool", "boolean[]"),
        ("_float8", "double precision[]"),
        ("_numeric", "numeric[]"),
        ("_varchar", "character varying[]"),
        ("_bpchar", "character[]"),
        ("_uuid", "uuid[]"),
        ("_jsonb", "jsonb[]"),
        # Multi-dimensional arrays (format_type uses [][] notation)
        ("integer[][]", "integer[][]"),
        ("text[][]", "text[][]"),
    ],
)
def test_array_types(raw: str, expected: str) -> None:
    """Array suffixes must be preserved; leading-underscore form is converted to []."""
    assert normalize_type(raw) == expected


# ===========================================================================
# Quoted "char" internal type
# ===========================================================================


@pytest.mark.unit
def test_quoted_char_is_preserved() -> None:
    """The internal ``\"char\"`` single-byte type must pass through unchanged."""
    assert normalize_type('"char"') == '"char"'


@pytest.mark.unit
def test_quoted_char_with_surrounding_whitespace() -> None:
    """Whitespace around ``\"char\"`` must be trimmed but value preserved."""
    assert normalize_type('  "char"  ') == '"char"'


# ===========================================================================
# Unknown / user-defined type pass-through
# ===========================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    [
        "myschema.mytype",
        "hstore",
        "ltree",
        "citext",
        "geography",
        "geometry",
        "user_defined_enum",
        "public.order_status",
    ],
)
def test_unknown_types_pass_through(raw: str) -> None:
    """Unknown or user-defined type names must be returned unchanged."""
    assert normalize_type(raw) == raw


# ===========================================================================
# Whitespace edge cases
# ===========================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  integer  ", "integer"),
        ("  int4  ", "integer"),
        ("  character varying(255)  ", "character varying(255)"),
        ("  boolean  ", "boolean"),
    ],
)
def test_whitespace_handling(raw: str, expected: str) -> None:
    """Leading/trailing whitespace must be stripped before canonicalization."""
    assert normalize_type(raw) == expected


# ===========================================================================
# Case sensitivity
# ===========================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # format_type always returns lowercase for built-in types; test anyway
        ("INTEGER", "integer"),
        ("INT4", "integer"),
        ("BOOL", "boolean"),
        ("FLOAT8", "double precision"),
        ("VARCHAR", "character varying"),
        ("NUMERIC", "numeric"),
    ],
)
def test_case_insensitive_lookup(raw: str, expected: str) -> None:
    """Alias lookup must be case-insensitive (format_type is lowercase but guard)."""
    assert normalize_type(raw) == expected


# ===========================================================================
# Real-world format_type outputs (regression / integration-style sanity)
# ===========================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Typical columns.sql outputs
        ("integer", "integer"),
        ("bigint", "bigint"),
        ("smallint", "smallint"),
        ("boolean", "boolean"),
        ("text", "text"),
        ("character varying(255)", "character varying(255)"),
        ("character varying", "character varying"),
        ("character(1)", "character(1)"),
        ("numeric(10,2)", "numeric(10,2)"),
        ("double precision", "double precision"),
        ("real", "real"),
        ("timestamp without time zone", "timestamp without time zone"),
        ("timestamp with time zone", "timestamp with time zone"),
        ("date", "date"),
        ("time without time zone", "time without time zone"),
        ("time with time zone", "time with time zone"),
        ("interval", "interval"),
        ("uuid", "uuid"),
        ("json", "json"),
        ("jsonb", "jsonb"),
        ("bytea", "bytea"),
        ("inet", "inet"),
        ("cidr", "cidr"),
        # Aliases that format_type may return depending on pg version / OID
        ("int4", "integer"),
        ("int8", "bigint"),
        ("int2", "smallint"),
        ("float4", "real"),
        ("float8", "double precision"),
        ("bool", "boolean"),
        ("bpchar", "character"),
        ("bpchar(5)", "character(5)"),
        ("varchar", "character varying"),
        ("varchar(100)", "character varying(100)"),
        ("decimal", "numeric"),
        ("decimal(15,4)", "numeric(15,4)"),
        ("timetz", "time with time zone"),
        ("timestamptz", "timestamp with time zone"),
        # Array variants
        ("_int4", "integer[]"),
        ("_text", "text[]"),
        ("_bool", "boolean[]"),
        ("integer[]", "integer[]"),
        ("text[]", "text[]"),
        ('"char"', '"char"'),
    ],
)
def test_real_world_format_type_outputs(raw: str, expected: str) -> None:
    """Sanity check against the full range of format_type outputs."""
    assert normalize_type(raw) == expected
