"""Tests for domain models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.models import ConnectionInfo, Profile


def _conn(**kwargs) -> ConnectionInfo:
    defaults = {"host": "localhost", "database": "testdb", "user": "user"}
    return ConnectionInfo(**{**defaults, **kwargs})


class TestConnectionInfo:
    def test_display_hides_password(self):
        c = _conn(password="secret")
        assert "secret" not in c.display()
        assert "postgres://" in c.display()

    def test_dsn_includes_password(self):
        c = _conn(password="secret")
        assert "secret" in c.dsn()

    def test_dsn_no_password(self):
        c = _conn()
        assert ":@" not in c.dsn()

    def test_default_port(self):
        c = _conn()
        assert c.port == 5432

    def test_frozen(self):
        c = _conn()
        with pytest.raises(ValidationError):
            c.host = "other"  # type: ignore[misc]


class TestProfile:
    def test_default_schemas(self):
        p = Profile(name="test", source=_conn(), target=_conn(host="remote"))
        assert p.schemas == ["public"]

    def test_summary(self):
        p = Profile(name="test", source=_conn(host="src"), target=_conn(host="tgt"))
        assert "src" in p.summary()
        assert "tgt" in p.summary()

    def test_frozen(self):
        p = Profile(name="test", source=_conn(), target=_conn(host="remote"))
        with pytest.raises(ValidationError):
            p.name = "other"  # type: ignore[misc]
