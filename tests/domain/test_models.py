"""Tests for domain models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.models import ConnectionInfo, Profile


def _conn(
    host: str = "localhost", database: str = "mydb", user: str = "admin"
) -> ConnectionInfo:
    return ConnectionInfo(host=host, database=database, user=user)


class TestConnectionInfo:
    def test_display(self) -> None:
        conn = _conn()
        assert conn.display() == "postgres://admin@localhost:5432/mydb"

    def test_dsn_no_password(self) -> None:
        conn = _conn()
        assert conn.dsn() == "postgresql://admin@localhost:5432/mydb"

    def test_dsn_with_password(self) -> None:
        conn = ConnectionInfo(
            host="localhost", database="mydb", user="admin", password="secret"
        )
        assert conn.dsn() == "postgresql://admin:secret@localhost:5432/mydb"

    def test_custom_port(self) -> None:
        conn = ConnectionInfo(host="db", port=5433, database="app", user="u")
        assert conn.display() == "postgres://u@db:5433/app"

    def test_frozen(self) -> None:
        conn = _conn()
        with pytest.raises((ValidationError, TypeError)):
            conn.host = "other"  # type: ignore[misc]


class TestProfile:
    def test_summary(self) -> None:
        p = Profile(name="test", source=_conn("source.db"), target=_conn("target.db"))
        assert p.summary() == "source.db / target.db"

    def test_defaults(self) -> None:
        p = Profile(name="test", source=_conn(), target=_conn())
        assert p.schemas == ["public"]
        assert p.ignore_patterns == []
        assert p.mode == "schema-only"

    def test_custom_schemas(self) -> None:
        p = Profile(
            name="test",
            source=_conn(),
            target=_conn(),
            schemas=["public", "billing"],
        )
        assert p.schemas == ["public", "billing"]

    def test_frozen(self) -> None:
        p = Profile(name="test", source=_conn(), target=_conn())
        with pytest.raises((ValidationError, TypeError)):
            p.name = "other"  # type: ignore[misc]

    def test_model_validate(self) -> None:
        data = {
            "name": "dev → staging",
            "source": {
                "host": "localhost",
                "port": 5432,
                "database": "dev",
                "user": "u",
            },
            "target": {
                "host": "staging",
                "port": 5432,
                "database": "app",
                "user": "app",
            },
            "schemas": ["public", "billing"],
            "ignore_patterns": ["temp_*"],
            "mode": "schema-only",
        }
        p = Profile.model_validate(data)
        assert p.name == "dev → staging"
        assert p.source.host == "localhost"
        assert p.ignore_patterns == ["temp_*"]
