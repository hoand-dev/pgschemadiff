import pytest

from pgschemadiff.application.sql_emit.quoting import (
    quote_ident,
    quote_literal,
    quote_qualified,
)
from pgschemadiff.domain.identity import QualifiedName
from pgschemadiff.shared.errors import MigrationError


def test_quote_ident_always_quotes_and_preserves_case_and_keywords() -> None:
    assert quote_ident("MixedCase") == '"MixedCase"'
    assert quote_ident("select") == '"select"'
    assert quote_ident("user") == '"user"'


def test_quote_ident_doubles_embedded_quotes() -> None:
    assert quote_ident('say "hi"') == '"say ""hi"""'


def test_quote_ident_allows_exactly_63_utf8_bytes() -> None:
    value = "é" * 31 + "a"

    assert len(value.encode("utf-8")) == 63
    assert quote_ident(value) == f'"{value}"'


def test_quote_ident_rejects_more_than_63_utf8_bytes() -> None:
    value = "é" * 32

    assert len(value.encode("utf-8")) == 64
    with pytest.raises(MigrationError):
        quote_ident(value)


@pytest.mark.parametrize("value", ["", "has\x00nul"])
def test_quote_ident_rejects_empty_and_nul(value: str) -> None:
    with pytest.raises(MigrationError):
        quote_ident(value)


def test_quote_qualified_quotes_components_separately() -> None:
    name = QualifiedName(namespace="a.b", name="x.y")

    assert quote_qualified(name) == '"a.b"."x.y"'


def test_quote_literal_doubles_apostrophes() -> None:
    assert quote_literal("it's a test") == "'it''s a test'"


def test_quote_literal_keeps_backslashes_literal() -> None:
    assert quote_literal(r"C:\temp\file") == r"'C:\temp\file'"


def test_quote_literal_rejects_nul() -> None:
    with pytest.raises(MigrationError):
        quote_literal("has\x00nul")
