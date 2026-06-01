"""Unit tests for ``pgschemadiff.domain.ports`` (task P1-DOM-08)."""

from __future__ import annotations

import importlib
import inspect

import pytest

import pgschemadiff.domain.ports as ports_module
from pgschemadiff.domain.database import Database
from pgschemadiff.domain.ports import MigrationWriter, SchemaInspector

# ---------------------------------------------------------------------------
# SchemaInspector Protocol
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_schema_inspector_is_runtime_checkable() -> None:
    # runtime_checkable allows isinstance checks against the protocol
    assert hasattr(SchemaInspector, "__protocol_attrs__")


@pytest.mark.unit
def test_schema_inspector_has_inspect_method() -> None:
    assert "inspect" in SchemaInspector.__protocol_attrs__


@pytest.mark.unit
def test_schema_inspector_inspect_is_coroutine_function() -> None:
    # The protocol's inspect method must be defined as async def
    method = SchemaInspector.inspect
    assert inspect.iscoroutinefunction(method)


@pytest.mark.unit
def test_non_inspector_fails_isinstance_check() -> None:
    class NotAnInspector:
        pass

    # runtime_checkable only checks method presence, not signatures
    # An object without .inspect should not satisfy the protocol
    obj = NotAnInspector()
    assert not isinstance(obj, SchemaInspector)


@pytest.mark.unit
def test_concrete_inspector_satisfies_protocol() -> None:
    class StubInspector:
        async def inspect(self) -> Database:
            return Database(name="stub")

    stub = StubInspector()
    assert isinstance(stub, SchemaInspector)


# ---------------------------------------------------------------------------
# MigrationWriter Protocol
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_migration_writer_is_runtime_checkable() -> None:
    assert hasattr(MigrationWriter, "__protocol_attrs__")


@pytest.mark.unit
def test_migration_writer_has_write_method() -> None:
    assert "write" in MigrationWriter.__protocol_attrs__


@pytest.mark.unit
def test_migration_writer_write_is_coroutine_function() -> None:
    method = MigrationWriter.write
    assert inspect.iscoroutinefunction(method)


@pytest.mark.unit
def test_non_writer_fails_isinstance_check() -> None:
    class NotAWriter:
        pass

    obj = NotAWriter()
    assert not isinstance(obj, MigrationWriter)


@pytest.mark.unit
def test_concrete_writer_satisfies_protocol() -> None:
    class StubWriter:
        async def write(self, migration_sql: str, *, label: str) -> str:
            return f"/migrations/{label}.sql"

    stub = StubWriter()
    assert isinstance(stub, MigrationWriter)


# ---------------------------------------------------------------------------
# Protocol — no IO / framework imports
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_ports_module_does_not_import_asyncio() -> None:
    """The domain layer must not import asyncio directly."""
    # Reload to ensure we see the real module namespace, not a cached version.
    mod = importlib.reload(ports_module)
    assert "asyncio" not in dir(mod)


@pytest.mark.unit
def test_ports_module_does_not_import_psycopg() -> None:
    mod = importlib.reload(ports_module)
    assert "psycopg" not in dir(mod)
