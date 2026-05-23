"""Tests for domain models."""

from __future__ import annotations

import pytest

from pgschemadiff.domain.models import ConnectionInfo, Profile


def test_connection_info_display_hides_password() -> None:
    conn = ConnectionInfo(
        host="db.example.com", port=5432, database="mydb", user="alice", password="secret"
    )
    assert "secret" not in conn.display()
    assert "alice@db.example.com:5432/mydb" in conn.display()


def test_connection_info_dsn_includes_password() -> None:
    conn = ConnectionInfo(host="localhost", database="testdb", user="bob", password="pw123")
    assert "pw123" in conn.dsn()


def test_connection_info_dsn_no_password() -> None:
    conn = ConnectionInfo(host="localhost", database="testdb", user="bob")
    dsn = conn.dsn()
    assert ":@" not in dsn
    assert "bob@localhost" in dsn


def test_profile_defaults() -> None:
    src = ConnectionInfo(host="src", database="db", user="u")
    tgt = ConnectionInfo(host="tgt", database="db", user="u")
    p = Profile(name="test", source=src, target=tgt)
    assert p.schemas == ["public"]
    assert p.ignore_patterns == []
    assert p.mode == "schema-only"


def test_profile_summary() -> None:
    src = ConnectionInfo(host="src-host", database="db", user="u")
    tgt = ConnectionInfo(host="tgt-host", database="db", user="u")
    p = Profile(name="test", source=src, target=tgt)
    assert "src-host" in p.summary()
    assert "tgt-host" in p.summary()


def test_profile_is_frozen() -> None:
    src = ConnectionInfo(host="src", database="db", user="u")
    tgt = ConnectionInfo(host="tgt", database="db", user="u")
    p = Profile(name="test", source=src, target=tgt)
    with pytest.raises(Exception):
        p.name = "changed"  # type: ignore[misc]
