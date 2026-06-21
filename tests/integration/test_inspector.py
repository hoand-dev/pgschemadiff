"""Integration tests for ``PgCatalogInspector`` — task P1-TEST-02.

Exercises ``PgCatalogInspector.inspect()`` against a real PostgreSQL 18 instance
provided by the session-scoped testcontainer fixture in ``conftest.py``
(ADR-0010 strategy 3).

Each test function creates a known schema in a fresh ``test_<uuid>`` database
(via the ``pg_test_dsn`` fixture), runs the inspector, and asserts the returned
``Database`` model matches the expected structure.

Integration tests are marked ``@pytest.mark.integration``; they require a live
PostgreSQL container and are validated by the CI
"Integration tests (PostgreSQL 18)" job.  They CANNOT run locally without Docker.
"""

from __future__ import annotations

import psycopg
import pytest

from pgschemadiff.domain.column import GeneratedTiming
from pgschemadiff.domain.constraint import (
    CheckConstraint,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    UniqueConstraint,
)
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.identity import QualifiedName
from pgschemadiff.domain.index import IndexMethod
from pgschemadiff.domain.ports import SchemaInspector
from pgschemadiff.infrastructure.postgres.inspector import PgCatalogInspector
from pgschemadiff.infrastructure.postgres.pool import Pool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup(dsn: str, ddl: str) -> None:
    """Execute DDL in the test database synchronously (psycopg 3, autocommit)."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(ddl)


async def _inspect(dsn: str, schemas: list[str] | None = None) -> Database:
    """Open a pool, run the inspector, and return the Database snapshot."""
    async with Pool(dsn) as pool:
        inspector = PgCatalogInspector(pool, schemas=schemas)
        return await inspector.inspect()


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_inspector_satisfies_schema_inspector_protocol(pg_test_dsn: str) -> None:
    """``PgCatalogInspector`` must satisfy the ``SchemaInspector`` Protocol."""
    async with Pool(pg_test_dsn) as pool:
        inspector = PgCatalogInspector(pool)
        assert isinstance(inspector, SchemaInspector)


# ---------------------------------------------------------------------------
# Empty database
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_empty_database_returns_database_object(pg_test_dsn: str) -> None:
    """An empty database (public schema only) should return a valid Database."""
    db = await _inspect(pg_test_dsn)

    assert isinstance(db, Database)
    assert db.name == "inspected"


@pytest.mark.integration
async def test_empty_database_has_public_schema(pg_test_dsn: str) -> None:
    """A fresh database always has the ``public`` schema."""
    db = await _inspect(pg_test_dsn)

    schema_names = {s.name for s in db.schemas}
    assert "public" in schema_names


@pytest.mark.integration
async def test_empty_database_has_no_tables(pg_test_dsn: str) -> None:
    """A fresh database has no user tables."""
    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    assert public.tables == ()


# ---------------------------------------------------------------------------
# Single plain table — tables + columns
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_single_table_is_present(pg_test_dsn: str) -> None:
    """A table created in the DB shows up in the Database snapshot."""
    _setup(
        pg_test_dsn,
        "CREATE TABLE public.users (id bigint NOT NULL, name text NOT NULL);",
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    table_names = {t.ref.qname.name for t in public.tables}
    assert "users" in table_names


@pytest.mark.integration
async def test_column_names_are_returned(pg_test_dsn: str) -> None:
    """Column names round-trip through the inspector correctly."""
    _setup(
        pg_test_dsn,
        "CREATE TABLE public.products ("
        "id bigint NOT NULL, sku text NOT NULL, price numeric(10,2)"
        ");",
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    table = public.table_by_name("products")
    assert table is not None
    col_names = {c.name for c in table.columns}
    assert col_names == {"id", "sku", "price"}


@pytest.mark.integration
async def test_column_order_matches_ordinal_position(pg_test_dsn: str) -> None:
    """Columns in the returned Table are sorted by their 1-based position."""
    _setup(
        pg_test_dsn,
        "CREATE TABLE public.items (a int, b int, c int, d int);",
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    table = public.table_by_name("items")
    assert table is not None
    positions = [col.position for col in table.columns]
    assert positions == sorted(positions)


@pytest.mark.integration
async def test_nullable_column_flag(pg_test_dsn: str) -> None:
    """nullable=True for a nullable column, False for NOT NULL."""
    _setup(
        pg_test_dsn,
        "CREATE TABLE public.mixed (req text NOT NULL, opt text);",
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    table = public.table_by_name("mixed")
    assert table is not None
    by_name = {c.name: c for c in table.columns}
    assert by_name["req"].nullable is False
    assert by_name["opt"].nullable is True


@pytest.mark.integration
async def test_column_with_default_expression(pg_test_dsn: str) -> None:
    """A column with a DEFAULT expression has a non-None default_expr."""
    _setup(
        pg_test_dsn,
        "CREATE TABLE public.events (id bigint, created_at timestamptz DEFAULT now());",
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    table = public.table_by_name("events")
    assert table is not None
    by_name = {c.name: c for c in table.columns}
    assert by_name["created_at"].default_expr is not None
    assert by_name["id"].default_expr is None


# ---------------------------------------------------------------------------
# Identity column
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_identity_column_is_detected(pg_test_dsn: str) -> None:
    """A ``GENERATED ALWAYS AS IDENTITY`` column has ``is_identity=True``."""
    _setup(
        pg_test_dsn,
        "CREATE TABLE public.ids (id bigint GENERATED ALWAYS AS IDENTITY, val text);",
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    table = public.table_by_name("ids")
    assert table is not None
    by_name = {c.name: c for c in table.columns}
    assert by_name["id"].is_identity is True
    assert by_name["val"].is_identity is False


@pytest.mark.integration
async def test_identity_column_generated_always(pg_test_dsn: str) -> None:
    """``GENERATED ALWAYS`` identity has ``GeneratedTiming.ALWAYS``."""
    _setup(
        pg_test_dsn,
        "CREATE TABLE public.gen_always (id bigint GENERATED ALWAYS AS IDENTITY);",
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    table = public.table_by_name("gen_always")
    assert table is not None
    col = table.columns[0]
    assert col.identity is not None
    assert col.identity.generated == GeneratedTiming.ALWAYS


@pytest.mark.integration
async def test_identity_column_generated_by_default(pg_test_dsn: str) -> None:
    """``GENERATED BY DEFAULT`` identity has ``GeneratedTiming.BY_DEFAULT``."""
    _setup(
        pg_test_dsn,
        "CREATE TABLE public.gen_default (id bigint GENERATED BY DEFAULT AS IDENTITY);",
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    table = public.table_by_name("gen_default")
    assert table is not None
    col = table.columns[0]
    assert col.identity is not None
    assert col.identity.generated == GeneratedTiming.BY_DEFAULT


# ---------------------------------------------------------------------------
# Primary key constraint
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_primary_key_constraint_detected(pg_test_dsn: str) -> None:
    """A ``PRIMARY KEY`` constraint is present in the table's constraint list."""
    _setup(
        pg_test_dsn,
        "CREATE TABLE public.orders (id bigint PRIMARY KEY, total numeric);",
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    table = public.table_by_name("orders")
    assert table is not None
    pk_constraints = [c for c in table.constraints if isinstance(c, PrimaryKeyConstraint)]
    assert len(pk_constraints) == 1


@pytest.mark.integration
async def test_primary_key_constraint_column_name(pg_test_dsn: str) -> None:
    """The PK constraint lists the correct column name."""
    _setup(
        pg_test_dsn,
        "CREATE TABLE public.accounts (account_id bigint PRIMARY KEY, name text);",
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    table = public.table_by_name("accounts")
    assert table is not None
    pk = next(c for c in table.constraints if isinstance(c, PrimaryKeyConstraint))
    assert "account_id" in pk.columns


@pytest.mark.integration
async def test_composite_primary_key(pg_test_dsn: str) -> None:
    """A composite PK lists all key columns."""
    _setup(
        pg_test_dsn,
        "CREATE TABLE public.order_items ("
        "  order_id bigint NOT NULL,"
        "  item_id bigint NOT NULL,"
        "  qty int,"
        "  PRIMARY KEY (order_id, item_id)"
        ");",
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    table = public.table_by_name("order_items")
    assert table is not None
    pk = next(c for c in table.constraints if isinstance(c, PrimaryKeyConstraint))
    assert set(pk.columns) == {"order_id", "item_id"}


# ---------------------------------------------------------------------------
# Unique constraint
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_unique_constraint_detected(pg_test_dsn: str) -> None:
    """A ``UNIQUE`` constraint is present in the table's constraint list."""
    _setup(
        pg_test_dsn,
        "CREATE TABLE public.members (  id bigint PRIMARY KEY,  email text UNIQUE NOT NULL);",
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    table = public.table_by_name("members")
    assert table is not None
    uniq_constraints = [c for c in table.constraints if isinstance(c, UniqueConstraint)]
    assert len(uniq_constraints) == 1
    assert "email" in uniq_constraints[0].columns


# ---------------------------------------------------------------------------
# Check constraint
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_check_constraint_detected(pg_test_dsn: str) -> None:
    """A ``CHECK`` constraint is present and its expression is non-empty."""
    _setup(
        pg_test_dsn,
        "CREATE TABLE public.scores ("
        "  id bigint PRIMARY KEY,"
        "  value int NOT NULL CHECK (value >= 0 AND value <= 100)"
        ");",
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    table = public.table_by_name("scores")
    assert table is not None
    check_constraints = [c for c in table.constraints if isinstance(c, CheckConstraint)]
    assert len(check_constraints) == 1
    assert check_constraints[0].expression != ""


# ---------------------------------------------------------------------------
# Foreign key constraint
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_foreign_key_constraint_detected(pg_test_dsn: str) -> None:
    """A ``FOREIGN KEY`` referencing another table is captured correctly."""
    _setup(
        pg_test_dsn,
        """
        CREATE TABLE public.departments (
            dept_id bigint PRIMARY KEY,
            name text NOT NULL
        );
        CREATE TABLE public.employees (
            emp_id bigint PRIMARY KEY,
            dept_id bigint NOT NULL REFERENCES public.departments(dept_id),
            name text NOT NULL
        );
        """,
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    table = public.table_by_name("employees")
    assert table is not None
    fk_constraints = [c for c in table.constraints if isinstance(c, ForeignKeyConstraint)]
    assert len(fk_constraints) == 1


@pytest.mark.integration
async def test_foreign_key_references_correct_table(pg_test_dsn: str) -> None:
    """The FK constraint names the correct referenced table and columns."""
    _setup(
        pg_test_dsn,
        """
        CREATE TABLE public.categories (
            cat_id bigint PRIMARY KEY,
            label text NOT NULL
        );
        CREATE TABLE public.articles (
            art_id bigint PRIMARY KEY,
            cat_id bigint NOT NULL REFERENCES public.categories(cat_id) ON DELETE CASCADE,
            title text NOT NULL
        );
        """,
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    table = public.table_by_name("articles")
    assert table is not None
    fk = next(c for c in table.constraints if isinstance(c, ForeignKeyConstraint))
    assert fk.ref_table == "categories"
    assert fk.ref_namespace == "public"
    assert "cat_id" in fk.columns
    assert "cat_id" in fk.ref_columns


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_explicit_index_is_captured(pg_test_dsn: str) -> None:
    """A CREATE INDEX shows up in the schema's index list."""
    _setup(
        pg_test_dsn,
        """
        CREATE TABLE public.logs (
            id bigint PRIMARY KEY,
            level text NOT NULL,
            message text
        );
        CREATE INDEX logs_level_idx ON public.logs (level);
        """,
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    index_names = {idx.ref.qname.name for idx in public.indexes}
    assert "logs_level_idx" in index_names


@pytest.mark.integration
async def test_index_method_is_btree_by_default(pg_test_dsn: str) -> None:
    """An index created without USING defaults to btree."""
    _setup(
        pg_test_dsn,
        """
        CREATE TABLE public.nodes (
            id bigint PRIMARY KEY,
            code text NOT NULL
        );
        CREATE INDEX nodes_code_idx ON public.nodes (code);
        """,
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    idx = next(
        (i for i in public.indexes if i.ref.qname.name == "nodes_code_idx"),
        None,
    )
    assert idx is not None
    assert idx.method == IndexMethod.BTREE


@pytest.mark.integration
async def test_unique_index_flag(pg_test_dsn: str) -> None:
    """A UNIQUE index has ``unique=True``; a plain one has ``unique=False``."""
    _setup(
        pg_test_dsn,
        """
        CREATE TABLE public.things (
            id bigint PRIMARY KEY,
            code text NOT NULL,
            tag text
        );
        CREATE UNIQUE INDEX things_code_uidx ON public.things (code);
        CREATE INDEX things_tag_idx ON public.things (tag);
        """,
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    idxs = {i.ref.qname.name: i for i in public.indexes}
    assert idxs["things_code_uidx"].unique is True
    assert idxs["things_tag_idx"].unique is False


@pytest.mark.integration
async def test_index_key_column_name(pg_test_dsn: str) -> None:
    """The index key column list reflects the columns used in CREATE INDEX."""
    _setup(
        pg_test_dsn,
        """
        CREATE TABLE public.widgets (
            id bigint PRIMARY KEY,
            name text NOT NULL,
            color text
        );
        CREATE INDEX widgets_name_color_idx ON public.widgets (name, color);
        """,
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    idx = next(
        (i for i in public.indexes if i.ref.qname.name == "widgets_name_color_idx"),
        None,
    )
    assert idx is not None
    col_names = {kc.column_name for kc in idx.key_columns if kc.column_name}
    assert col_names == {"name", "color"}


@pytest.mark.integration
async def test_partial_index_has_predicate(pg_test_dsn: str) -> None:
    """A partial index (WHERE clause) has a non-None predicate."""
    _setup(
        pg_test_dsn,
        """
        CREATE TABLE public.tasks (
            id bigint PRIMARY KEY,
            done boolean NOT NULL DEFAULT false,
            title text
        );
        CREATE INDEX tasks_active_idx ON public.tasks (title) WHERE NOT done;
        """,
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    idx = next(
        (i for i in public.indexes if i.ref.qname.name == "tasks_active_idx"),
        None,
    )
    assert idx is not None
    assert idx.predicate is not None


# ---------------------------------------------------------------------------
# Multiple tables
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_multiple_tables_are_all_present(pg_test_dsn: str) -> None:
    """All tables created in the schema appear in the snapshot."""
    _setup(
        pg_test_dsn,
        """
        CREATE TABLE public.alpha (id int PRIMARY KEY);
        CREATE TABLE public.beta  (id int PRIMARY KEY);
        CREATE TABLE public.gamma (id int PRIMARY KEY);
        """,
    )

    db = await _inspect(pg_test_dsn)

    public = db.schema_by_name("public")
    assert public is not None
    table_names = {t.ref.qname.name for t in public.tables}
    assert {"alpha", "beta", "gamma"}.issubset(table_names)


# ---------------------------------------------------------------------------
# Custom schema
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_custom_schema_appears_in_snapshot(pg_test_dsn: str) -> None:
    """A user-created schema appears in the Database schemas list."""
    _setup(
        pg_test_dsn,
        """
        CREATE SCHEMA reporting;
        CREATE TABLE reporting.summary (id bigint PRIMARY KEY, total numeric);
        """,
    )

    db = await _inspect(pg_test_dsn)

    schema_names = {s.name for s in db.schemas}
    assert "reporting" in schema_names


@pytest.mark.integration
async def test_custom_schema_table_is_inspected(pg_test_dsn: str) -> None:
    """A table inside a custom schema is correctly associated with that schema."""
    _setup(
        pg_test_dsn,
        """
        CREATE SCHEMA analytics;
        CREATE TABLE analytics.events (
            event_id bigint PRIMARY KEY,
            kind text NOT NULL
        );
        """,
    )

    db = await _inspect(pg_test_dsn)

    schema = db.schema_by_name("analytics")
    assert schema is not None
    table = schema.table_by_name("events")
    assert table is not None
    assert table.ref.qname.namespace == "analytics"


# ---------------------------------------------------------------------------
# Schema filter
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_schema_filter_excludes_other_schemas(pg_test_dsn: str) -> None:
    """When ``schemas=["public"]`` is set, tables in other schemas are excluded."""
    _setup(
        pg_test_dsn,
        """
        CREATE SCHEMA private;
        CREATE TABLE public.visible (id bigint PRIMARY KEY);
        CREATE TABLE private.hidden (id bigint PRIMARY KEY);
        """,
    )

    db = await _inspect(pg_test_dsn, schemas=["public"])

    schema_names = {s.name for s in db.schemas}
    assert "public" in schema_names
    assert "private" not in schema_names


@pytest.mark.integration
async def test_schema_filter_keeps_target_schema(pg_test_dsn: str) -> None:
    """When ``schemas=["target"]`` is set, tables in that schema are present."""
    _setup(
        pg_test_dsn,
        """
        CREATE SCHEMA target;
        CREATE TABLE target.data (id bigint PRIMARY KEY, payload text);
        """,
    )

    db = await _inspect(pg_test_dsn, schemas=["target"])

    schema = db.schema_by_name("target")
    assert schema is not None
    assert schema.table_by_name("data") is not None


# ---------------------------------------------------------------------------
# Extensions
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_installed_extension_is_present(pg_test_dsn: str) -> None:
    """An installed extension appears in ``Database.extensions``."""
    _setup(pg_test_dsn, "CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    db = await _inspect(pg_test_dsn)

    ext_names = {e.name for e in db.extensions}
    assert "pgcrypto" in ext_names


@pytest.mark.integration
async def test_installed_extension_has_version(pg_test_dsn: str) -> None:
    """The installed extension has a non-empty version string."""
    _setup(pg_test_dsn, "CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    db = await _inspect(pg_test_dsn)

    ext = db.extension_by_name("pgcrypto")
    assert ext is not None
    assert ext.version != ""


# ---------------------------------------------------------------------------
# Database lookup helpers
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_table_by_qname_lookup(pg_test_dsn: str) -> None:
    """``Database.table_by_qname`` returns the correct table."""
    _setup(
        pg_test_dsn,
        "CREATE TABLE public.lookup_me (id bigint PRIMARY KEY);",
    )

    db = await _inspect(pg_test_dsn)

    qname = QualifiedName(namespace="public", name="lookup_me")
    table = db.table_by_qname(qname)
    assert table is not None
    assert table.ref.qname.name == "lookup_me"


@pytest.mark.integration
async def test_schema_by_name_returns_none_for_missing(pg_test_dsn: str) -> None:
    """``Database.schema_by_name`` returns ``None`` for a nonexistent schema."""
    db = await _inspect(pg_test_dsn)

    result = db.schema_by_name("nonexistent_xyz_schema")
    assert result is None


# ---------------------------------------------------------------------------
# all_tables / all_indexes helpers
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_all_tables_spans_multiple_schemas(pg_test_dsn: str) -> None:
    """``Database.all_tables()`` gathers tables from every schema."""
    _setup(
        pg_test_dsn,
        """
        CREATE SCHEMA ns_a;
        CREATE SCHEMA ns_b;
        CREATE TABLE ns_a.foo (id int PRIMARY KEY);
        CREATE TABLE ns_b.bar (id int PRIMARY KEY);
        """,
    )

    db = await _inspect(pg_test_dsn)

    all_names = {t.ref.qname.name for t in db.all_tables()}
    assert "foo" in all_names
    assert "bar" in all_names


@pytest.mark.integration
async def test_all_indexes_spans_multiple_schemas(pg_test_dsn: str) -> None:
    """``Database.all_indexes()`` gathers indexes from every schema."""
    _setup(
        pg_test_dsn,
        """
        CREATE SCHEMA idx_ns;
        CREATE TABLE idx_ns.data (id int PRIMARY KEY, val text);
        CREATE INDEX data_val_idx ON idx_ns.data (val);
        """,
    )

    db = await _inspect(pg_test_dsn)

    all_idx_names = {i.ref.qname.name for i in db.all_indexes()}
    assert "data_val_idx" in all_idx_names
