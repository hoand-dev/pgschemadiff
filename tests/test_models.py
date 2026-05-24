"""Tests for domain models."""

from __future__ import annotations

import pytest
from pgschemadiff.domain.models import ConnectionInfo, Profile


def _conn(host: str = "localhost", db: str = "mydb", user: str = "admin") -> ConnectionInfo:
    return ConnectionInfo(host=host, port=5432, database=db, user=user)


class TestConnectionInfo:
    def test_display_contains_user_host_db(self) -> None:
        conn = _conn()
        d = conn.display()
        assert "admin" in d
        assert "localhost" in d
        assert "mydb" in d

    def test_display_hides_password(self) -> None:
        conn = ConnectionInfo(host="h", port=5432, database="d", user="u", password="secret")
        assert "secret" not in conn.display()

    def test_dsn_includes_password(self) -> None:
        conn = ConnectionInfo(host="h", port=5432, database="d", user="u", password="s3cr3t")
        assert "s3cr3t" in conn.dsn()

    def test_dsn_no_password_when_empty(self) -> None:
        conn = ConnectionInfo(host="h", port=5432, database="d", user="u", password="")
        assert ":@" not in conn.dsn()

    def test_frozen(self) -> None:
        conn = _conn()
        with pytest.raises(Exception):
            conn.host = "other"  # type: ignore[misc]


class TestProfile:
    def test_summary_contains_hosts(self) -> None:
        src = _conn(host="source.db")
        tgt = _conn(host="target.db")
        p = Profile(name="test", source=src, target=tgt)
        assert "source.db" in p.summary()
        assert "target.db" in p.summary()

    def test_default_schemas(self) -> None:
        conn = _conn()
        p = Profile(name="p", source=conn, target=conn)
        assert p.schemas == ["public"]

    def test_default_mode(self) -> None:
        conn = _conn()
        p = Profile(name="p", source=conn, target=conn)
        assert p.mode == "schema-only"

    def test_frozen(self) -> None:
        conn = _conn()
        p = Profile(name="p", source=conn, target=conn)
        with pytest.raises(Exception):
            p.name = "other"  # type: ignore[misc]
