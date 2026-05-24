"""Tests for domain model layer."""

from __future__ import annotations

import pytest

from pgschemadiff.domain.models import ConnectionInfo, Profile


def test_connection_info_display_hides_password():
    conn = ConnectionInfo(host="db.local", port=5432, database="app", user="admin", password="secret")
    assert "secret" not in conn.display()
    assert "admin@db.local:5432/app" in conn.display()


def test_connection_info_dsn_includes_password():
    conn = ConnectionInfo(host="db.local", port=5432, database="app", user="admin", password="s3cr3t")
    assert "s3cr3t" in conn.dsn()


def test_connection_info_dsn_no_password():
    conn = ConnectionInfo(host="db.local", database="app", user="ci", password="")
    assert ":@" not in conn.dsn()
    assert "ci@db.local" in conn.dsn()


def test_profile_defaults():
    src = ConnectionInfo(host="a", database="db", user="u")
    tgt = ConnectionInfo(host="b", database="db", user="u")
    p = Profile(name="test", source=src, target=tgt)
    assert p.schemas == ["public"]
    assert p.ignore_patterns == []
    assert p.mode == "schema-only"


def test_profile_is_frozen():
    src = ConnectionInfo(host="a", database="db", user="u")
    tgt = ConnectionInfo(host="b", database="db", user="u")
    p = Profile(name="test", source=src, target=tgt)
    with pytest.raises(Exception):
        p.name = "mutated"  # type: ignore[misc]


def test_profile_summary():
    src = ConnectionInfo(host="src-host", database="db", user="u")
    tgt = ConnectionInfo(host="tgt-host", database="db", user="u")
    p = Profile(name="my profile", source=src, target=tgt)
    assert "src-host" in p.summary()
    assert "tgt-host" in p.summary()
