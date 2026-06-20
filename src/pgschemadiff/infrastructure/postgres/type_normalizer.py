"""PostgreSQL type name normalizer (task P1-INFRA-06).

``normalize_type`` maps a ``format_type(atttypid, atttypmod)`` output string to
a canonical PostgreSQL type name so that two schemas that are semantically
identical compare as equal regardless of how Postgres spells the type.

Design decisions
----------------
- Pure synchronous function — no IO, no async, no external dependencies.
- Lives in ``infrastructure/`` because it is PostgreSQL-specific knowledge;
  the domain layer receives only canonical strings.
- The alias table is explicit and well-commented to make audit/additions easy.
- Type modifiers such as ``(255)``, ``(10,2)`` are preserved on the base type.
- Array suffixes (``[]``, ``[3]``, ``[3][5]``) are stripped, normalised on the
  base type, then re-appended.
- ``"char"`` (the internal Postgres single-byte type with a quoted name) is
  distinguished from ``char``/``character`` by the double-quote wrapping that
  ``format_type`` emits.

Alias table
-----------
All aliases come from the PostgreSQL source file ``pg_type.dat``, the SQL
standard, or are common informal spellings that ``format_type`` may return:

  internal name (pg_type.typname) → canonical SQL name
  ────────────────────────────────────────────────────────────────────────
  int2, smallint              → smallint
  int4, int                   → integer
  int8, bigint                → bigint
  float4, real                → real
  float8, double precision    → double precision
  bool                        → boolean
  bpchar                      → character        (plain, no modifier)
  bpchar(n)                   → character(n)     (with modifier)
  varchar, varchar(n)         → character varying / character varying(n)
  decimal, decimal(p,s)       → numeric / numeric(p,s)
  timetz                      → time with time zone
  timestamptz                 → timestamp with time zone
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Alias table — maps lowercase bare type names (no modifiers, no array suffix)
# to their canonical SQL equivalents.
#
# Key: what ``format_type`` might return as the bare name (after stripping
#      modifiers and array suffixes), lowercased.
# Value: the canonical SQL name (mixed case preserved where SQL standard
#        specifies it, e.g. "double precision", "character varying").
# ---------------------------------------------------------------------------
_ALIAS_MAP: dict[str, str] = {
    # ── Integer types ────────────────────────────────────────────────────────
    "int2": "smallint",
    "smallint": "smallint",  # already canonical; identity entry
    "int4": "integer",
    "int": "integer",
    "integer": "integer",  # identity
    "int8": "bigint",
    "bigint": "bigint",  # identity
    # ── Floating-point types ─────────────────────────────────────────────────
    "float4": "real",
    "real": "real",  # identity
    "float8": "double precision",
    "double precision": "double precision",  # identity (two-word name)
    # ── Boolean ──────────────────────────────────────────────────────────────
    "bool": "boolean",
    "boolean": "boolean",  # identity
    # ── Character types ──────────────────────────────────────────────────────
    # bpchar is Postgres's internal name for CHAR(n); without a modifier it is
    # equivalent to character(1) but format_type returns "bpchar" or "character".
    "bpchar": "character",
    "character": "character",  # identity
    "char": "character",  # informal alias
    # varchar → character varying (Postgres canonical SQL form)
    "varchar": "character varying",
    "character varying": "character varying",  # identity
    # ── Numeric / decimal ────────────────────────────────────────────────────
    "decimal": "numeric",
    "numeric": "numeric",  # identity
    # ── Date/time ────────────────────────────────────────────────────────────
    "timetz": "time with time zone",
    "time with time zone": "time with time zone",  # identity
    "time without time zone": "time without time zone",  # identity
    "timestamptz": "timestamp with time zone",
    "timestamp with time zone": "timestamp with time zone",  # identity
    "timestamp without time zone": "timestamp without time zone",  # identity
    # ── Byte string ──────────────────────────────────────────────────────────
    "bytea": "bytea",  # identity; listed for completeness
    # ── Misc commonly seen ───────────────────────────────────────────────────
    "text": "text",  # identity
    "name": "name",  # identity (Postgres system catalog type)
    "oid": "oid",  # identity
    "uuid": "uuid",  # identity
    "json": "json",  # identity
    "jsonb": "jsonb",  # identity
    "xml": "xml",  # identity
    "inet": "inet",  # identity
    "cidr": "cidr",  # identity
    "macaddr": "macaddr",  # identity
    "macaddr8": "macaddr8",  # identity
    "bit": "bit",  # identity
    "bit varying": "bit varying",  # identity
    "date": "date",  # identity
    "interval": "interval",  # identity
    "money": "money",  # identity
    "point": "point",  # identity
    "line": "line",  # identity
    "lseg": "lseg",  # identity
    "box": "box",  # identity
    "path": "path",  # identity
    "polygon": "polygon",  # identity
    "circle": "circle",  # identity
    "tsvector": "tsvector",  # identity
    "tsquery": "tsquery",  # identity
    "pg_lsn": "pg_lsn",  # identity
    "txid_snapshot": "txid_snapshot",  # identity
}

# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

# Match a trailing array dimension suffix, e.g. "[]", "[3]", "[3][5]", "[][]".
# We capture everything from the first "[" to end-of-string.
_RE_ARRAY_SUFFIX = re.compile(r"(\[(?:\d*)\])+$")

# Match a trailing type modifier in parentheses, e.g. "(255)", "(10,2)", "(6)".
# The modifier immediately precedes the array suffix (if any).
_RE_MODIFIER = re.compile(r"\(([^)]+)\)$")

# The internal Postgres single-byte char type is spelled `"char"` with literal
# double-quote characters in format_type output.  We detect this before any
# lowercasing to avoid confusing it with CHAR / CHARACTER.
_QUOTED_CHAR_LITERAL = '"char"'


def normalize_type(raw: str) -> str:
    """Return the canonical SQL type name for a ``format_type()`` output string.

    Parameters
    ----------
    raw:
        The raw type string returned by ``format_type(atttypid, atttypmod)``,
        e.g. ``"character varying(255)"``, ``"int4"``, ``"_int4"``,
        ``"integer[]"``, ``"numeric(10,2)"``, ``'"char"'``, ``"bpchar"``.

    Returns
    -------
    str
        The canonical type name with modifier and array suffix preserved.
        Unknown types are returned unchanged (pass-through).

    Examples
    --------
    >>> normalize_type("int4")
    'integer'
    >>> normalize_type("character varying(255)")
    'character varying(255)'
    >>> normalize_type("_int4")
    'integer[]'
    >>> normalize_type("numeric(10,2)")
    'numeric(10,2)'
    >>> normalize_type('"char"')
    '"char"'
    """
    # ── 0. Handle the special quoted `"char"` internal type ──────────────────
    # format_type emits this with surrounding double-quotes; preserve as-is.
    if raw.strip() == _QUOTED_CHAR_LITERAL:
        return raw.strip()

    # ── 1. Handle the leading-underscore array notation from pg_catalog ───────
    # When format_type encounters an array type it may return "_typename" for
    # the element type (the underscore prefix is the pg_catalog convention for
    # array types of that element type).  Normalise to "typename[]".
    leading_underscore = raw.startswith("_") and not raw.startswith("__")
    if leading_underscore:
        raw = raw[1:] + "[]"

    # ── 2. Strip leading/trailing whitespace ──────────────────────────────────
    raw = raw.strip()

    # ── 3. Separate array suffix ──────────────────────────────────────────────
    array_suffix = ""
    m_array = _RE_ARRAY_SUFFIX.search(raw)
    if m_array:
        array_suffix = m_array.group(0)  # e.g. "[]" or "[3][5]"
        raw = raw[: m_array.start()]

    # ── 4. Separate type modifier ─────────────────────────────────────────────
    modifier = ""
    m_mod = _RE_MODIFIER.search(raw)
    if m_mod:
        modifier = m_mod.group(0)  # e.g. "(255)" or "(10,2)"
        raw = raw[: m_mod.start()]

    # ── 5. Normalise bare type name ───────────────────────────────────────────
    bare = raw.strip()
    bare_lower = bare.lower()
    canonical_bare = _ALIAS_MAP.get(bare_lower, bare)

    # ── 6. Re-assemble ────────────────────────────────────────────────────────
    return canonical_bare + modifier + array_suffix
