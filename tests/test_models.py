"""Tests for domain models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pgschemadiff.domain.models import ConnectionInfo, Profile


def test_connection_info_display() -> None:
    conn = ConnectionInfo(host="localhost", port=5432, database="mydb", user="alice")
    assert conn.display() == "postgres://alice@localhost:5432/mydb"


def test_connection_info_dsn_no_password() -> None:
    conn = ConnectionInfo(host="localhost", port=5432, database="mydb", user="alice")
    assert conn.dsn() == "postgresql://alice@localhost:5432/mydb"


def test_connection_info_dsn_with_password() -> None:
    conn = ConnectionInfo(host="db.example.com", port=5433, database="prod", user="app", password="s3cret")
    assert conn.dsn() == "postgresql://app:s3cret@db.example.com:5433/prod"


def test_connection_info_default_port() -> None:
    conn = ConnectionInfo(host="localhost", database="mydb", user="u")
    assert conn.port == 5432


def test_profile_defaults() -> None:
    src = ConnectionInfo(host="a", database="db", user="u")
    tgt = ConnectionInfo(host="b", database="db", user="u")
    profile = Profile(name="test", source=src, target=tgt)
    assert profile.schemas == ["public"]
    assert profile.ignore_patterns == []
    assert profile.mode == "schema-only"


def test_profile_summary() -> None:
    src = ConnectionInfo(host="source-host", database="db", user="u")
    tgt = ConnectionInfo(host="target-host", database="db", user="u")
    profile = Profile(name="p", source=src, target=tgt)
    assert profile.summary() == "source-host / target-host"


def test_profile_is_frozen() -> None:
    src = ConnectionInfo(host="a", database="db", user="u")
    tgt = ConnectionInfo(host="b", database="db", user="u")
    profile = Profile(name="p", source=src, target=tgt)
    with pytest.raises(ValidationError):
        profile.name = "changed"  # type: ignore[misc]


def test_connection_info_is_frozen() -> None:
    conn = ConnectionInfo(host="localhost", database="mydb", user="u")
    with pytest.raises(ValidationError):
        conn.host = "other"  # type: ignore[misc]
