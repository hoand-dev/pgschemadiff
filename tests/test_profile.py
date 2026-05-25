"""Tests for domain models."""

from __future__ import annotations

import pytest

from pgschemadiff.domain.models import ConnectionInfo, Profile


def test_connection_info_display_hides_password() -> None:
    c = ConnectionInfo(host="db.local", database="mydb", user="alice", password="secret")
    assert "secret" not in c.display()
    assert "alice@db.local" in c.display()


def test_connection_info_dsn_includes_password() -> None:
    c = ConnectionInfo(host="db.local", database="mydb", user="alice", password="secret")
    assert "secret" in c.dsn()


def test_connection_info_dsn_no_password() -> None:
    c = ConnectionInfo(host="db.local", database="mydb", user="alice")
    assert "@db.local" in c.dsn()
    assert ":@" not in c.dsn()


def test_profile_defaults() -> None:
    src = ConnectionInfo(host="a", database="db", user="u")
    tgt = ConnectionInfo(host="b", database="db", user="u")
    p = Profile(name="test", source=src, target=tgt)
    assert p.schemas == ["public"]
    assert p.ignore_patterns == []
    assert p.mode == "schema-only"


def test_profile_summary() -> None:
    src = ConnectionInfo(host="source-host", database="db", user="u")
    tgt = ConnectionInfo(host="target-host", database="db", user="u")
    p = Profile(name="test", source=src, target=tgt)
    assert "source-host" in p.summary()
    assert "target-host" in p.summary()


def test_profile_is_frozen() -> None:
    src = ConnectionInfo(host="a", database="db", user="u")
    tgt = ConnectionInfo(host="b", database="db", user="u")
    p = Profile(name="test", source=src, target=tgt)
    with pytest.raises(Exception):
        p.name = "changed"  # type: ignore[misc]
