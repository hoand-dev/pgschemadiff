"""Tests for domain models."""

from __future__ import annotations

import pytest

from pgschemadiff.domain.models import ConnectionInfo, Profile


def test_connection_info_display_hides_password():
    conn = ConnectionInfo(host="db.local", database="mydb", user="admin", password="secret")
    assert "secret" not in conn.display()
    assert "admin@db.local:5432/mydb" in conn.display()


def test_connection_info_dsn_includes_password():
    conn = ConnectionInfo(host="db.local", database="mydb", user="admin", password="secret")
    assert ":secret@" in conn.dsn()


def test_connection_info_dsn_no_password():
    conn = ConnectionInfo(host="db.local", database="mydb", user="admin")
    assert "@db.local" in conn.dsn()
    assert ":@" not in conn.dsn()


def test_connection_info_default_port():
    conn = ConnectionInfo(host="localhost", database="db", user="u")
    assert conn.port == 5432


def test_profile_defaults():
    src = ConnectionInfo(host="a", database="db1", user="u")
    tgt = ConnectionInfo(host="b", database="db2", user="u")
    p = Profile(name="test", source=src, target=tgt)
    assert p.schemas == ["public"]
    assert p.ignore_patterns == []
    assert p.mode == "schema-only"


def test_profile_summary():
    src = ConnectionInfo(host="source-host", database="db1", user="u")
    tgt = ConnectionInfo(host="target-host", database="db2", user="u")
    p = Profile(name="my-profile", source=src, target=tgt)
    assert "source-host" in p.summary()
    assert "target-host" in p.summary()


def test_profile_is_frozen():
    src = ConnectionInfo(host="a", database="db1", user="u")
    tgt = ConnectionInfo(host="b", database="db2", user="u")
    p = Profile(name="test", source=src, target=tgt)
    with pytest.raises(Exception):
        p.name = "changed"  # type: ignore[misc]
