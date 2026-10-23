"""SQL quoting helpers for PostgreSQL identifiers and string literals."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pgschemadiff.domain.identity import QualifiedName

_MAX_IDENTIFIER_BYTES = 63


def quote_ident(value: str) -> str:
    """Always double-quote a PostgreSQL identifier.

    PostgreSQL identifiers are limited to 63 bytes in the server encoding;
    this project uses UTF-8. Embedded double quotes are doubled.
    """
    if not value:
        raise MigrationError("Identifier must not be empty.")
    if "\x00" in value:
        raise MigrationError("Identifier must not contain NUL.")
    if len(value.encode("utf-8")) > _MAX_IDENTIFIER_BYTES:
        raise MigrationError("Identifier must not exceed 63 bytes in UTF-8.")

    return '"' + value.replace('"', '""') + '"'


def quote_qualified(name: QualifiedName) -> str:
    """Quote each component of a qualified name independently."""
    return f"{quote_ident(name.namespace)}.{quote_ident(name.name)}"


def quote_literal(value: str) -> str:
    """Quote a string literal, assuming PostgreSQL ``standard_conforming_strings=on``.

    This is PostgreSQL's default since 9.1: backslashes stay literal in
    ``'...'`` strings, so only embedded apostrophes are doubled. No ``E''``
    string is emitted.
    """
    if "\x00" in value:
        raise MigrationError("String literal must not contain NUL.")

    return "'" + value.replace("'", "''") + "'"
