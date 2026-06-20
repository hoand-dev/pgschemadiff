"""Application use case: inspect a database schema (task P1-CLI-01).

This module contains the ``inspect_schema`` use-case function.  It sits in
the application layer and depends only on the domain ``SchemaInspector``
Protocol — never on infrastructure concrete types.

The wiring (constructing the ``Pool`` and ``PgCatalogInspector``) happens in
the presentation layer (``presentation.cli.commands.inspect``), which passes
the already-constructed ``SchemaInspector`` here.

Usage::

    from pgschemadiff.application.inspect.inspect_schema import inspect_schema

    # In an async context — presentation wires the concrete inspector:
    json_output = await inspect_schema(inspector)
    print(json_output)

"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pgschemadiff.domain.ports import SchemaInspector


async def inspect_schema(inspector: SchemaInspector) -> str:
    """Run the schema inspector and return the ``Database`` snapshot as JSON.

    Parameters
    ----------
    inspector:
        Any object satisfying the :class:`~pgschemadiff.domain.ports.SchemaInspector`
        Protocol.  In production this will be ``PgCatalogInspector``; in tests it
        can be any async-callable stub.

    Returns
    -------
    str
        The fully-serialised ``Database`` aggregate as a UTF-8 JSON string with
        two-space indentation.

    Raises
    ------
    pgschemadiff.shared.errors.InspectionError
        Propagated from the infrastructure layer if the catalog query fails.
    """
    database = await inspector.inspect()
    return database.model_dump_json(indent=2)
