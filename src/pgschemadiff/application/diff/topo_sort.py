"""Generic topological sort using Kahn's algorithm (task P2-DIFF-08).

This module provides a single public function, :func:`topological_sort`, that
orders an arbitrary set of hashable nodes according to a caller-supplied
dependency mapping.  It is intentionally decoupled from every domain type so it
can be tested in isolation and reused by any future ordering need.

The downstream consumer (the diff engine, ``application/diff/engine.py``) will
call this function with a collection of :class:`~pgschemadiff.domain.delta.DeltaBase`
instances and pass ``DeltaBase.sort_key`` as the *key* callable for
deterministic tie-breaking.

Design notes
------------
* **Kahn's algorithm** — BFS over in-degrees — is used instead of DFS because
  it makes the "simultaneously ready" set explicit at each step, which lets us
  apply a total tie-breaking ordering to produce a stable, deterministic output
  regardless of dict insertion order or Python set iteration order.
* **Tie-breaking** — when several nodes simultaneously have in-degree 0 (all
  prerequisites satisfied), they are emitted in ascending order of
  ``key(node)``.  The caller controls this entirely; the diff engine passes
  ``DeltaBase.sort_key`` which is a collision-free ``tuple[str, ...]``.
* **Cycle detection** — if the BFS queue drains before all nodes are emitted,
  the remaining nodes (non-zero in-degree) form one or more cycles.
  :exc:`~pgschemadiff.shared.errors.CyclicDependencyError` is raised with a
  message that names all cycle members.
* **Input validation** — every prerequisite referenced in *dependencies* must
  appear in *nodes*.  Unknown prerequisites raise :exc:`ValueError` immediately
  so callers get a clear error instead of a silently incomplete graph.

Examples
--------
Simple linear chain (A → B → C, meaning B depends on A, C depends on B)::

    from pgschemadiff.application.diff.topo_sort import topological_sort

    result = topological_sort(
        ["A", "B", "C"],
        {"B": ["A"], "C": ["B"]},
        key=str,
    )
    assert result == ["A", "B", "C"]

Diamond (B and C depend on A; D depends on B and C)::

    result = topological_sort(
        ["A", "B", "C", "D"],
        {"B": ["A"], "C": ["A"], "D": ["B", "C"]},
        key=str,
    )
    assert result[0] == "A"
    assert result[-1] == "D"
    assert set(result[1:3]) == {"B", "C"}

Cycle raises ``CyclicDependencyError``::

    from pgschemadiff.shared.errors import CyclicDependencyError

    with pytest.raises(CyclicDependencyError):
        topological_sort(["X", "Y"], {"X": ["Y"], "Y": ["X"]}, key=str)
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

from pgschemadiff.shared.errors import CyclicDependencyError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def topological_sort[T](
    nodes: Iterable[T],
    dependencies: Mapping[T, Iterable[T]],
    *,
    key: Callable[[T], Any],
) -> list[T]:
    """Return *nodes* in dependency order using Kahn's algorithm.

    When multiple nodes are simultaneously ready (in-degree 0), they are
    emitted in ascending order of ``key(node)``, yielding a fully
    deterministic output regardless of dict or set iteration order.

    Parameters
    ----------
    nodes:
        All nodes that must appear in the output.  Every node referenced as a
        prerequisite in *dependencies* must also appear here; if a prerequisite
        is missing a :exc:`ValueError` is raised immediately.
    dependencies:
        A mapping from each node to an iterable of its *prerequisites* — the
        nodes that must appear **before** it in the final ordering.  Nodes that
        have no prerequisites may be omitted from the mapping entirely (they
        will be treated as having no prerequisites).  Self-loops (``node``
        listed as its own prerequisite) and multi-node cycles both raise
        :exc:`~pgschemadiff.shared.errors.CyclicDependencyError`.
    key:
        A callable that accepts a node and returns a value comparable with
        ``<``.  When several nodes simultaneously have all prerequisites
        satisfied the one with the smallest ``key`` value is emitted first.
        The diff engine passes ``DeltaBase.sort_key`` here; for plain strings
        ``str`` works.

    Returns
    -------
    list[T]
        All nodes in topological (dependency-respecting) order.  The result is
        a **new** list; the input iterables are not mutated.

    Raises
    ------
    ValueError
        If a node referenced as a prerequisite in *dependencies* does not
        appear in *nodes*.
    pgschemadiff.shared.errors.CyclicDependencyError
        If the dependency graph contains one or more cycles (including
        self-loops).  The error message names every node that participates
        in a cycle.
    """
    # Materialise the node set so we can do O(1) membership checks and build
    # a stable sorted list of all nodes later.
    node_list: list[T] = list(nodes)
    # Map node id → node object for O(1) reverse lookup
    id_to_node: dict[int, T] = {id(n): n for n in node_list}
    node_ids: set[int] = set(id_to_node)

    # ------------------------------------------------------------------
    # Validate: every prerequisite must be a known node
    # ------------------------------------------------------------------
    for node, prereqs in dependencies.items():
        for prereq in prereqs:
            if id(prereq) not in node_ids and not any(prereq == n for n in node_list):
                msg = (
                    f"Prerequisite {prereq!r} (required by {node!r}) "
                    "is not in the nodes iterable.  All prerequisites must "
                    "be members of 'nodes'."
                )
                raise ValueError(msg)

    # ------------------------------------------------------------------
    # Build adjacency list and in-degree table (Kahn's algorithm setup)
    # ------------------------------------------------------------------
    # adjacency[node_id] = list of node_ids that DEPEND ON node
    #   (i.e. node is a prerequisite for them — the forward edge in the
    #    "comes before" graph)
    adjacency: dict[int, list[int]] = {id(n): [] for n in node_list}
    in_degree: dict[int, int] = {id(n): 0 for n in node_list}

    for node, prereqs in dependencies.items():
        seen_prereqs: set[int] = set()
        for prereq in prereqs:
            # Resolve prereq to its canonical id (the one in node_list)
            prereq_id = _resolve_id(prereq, node_list)
            if prereq_id in seen_prereqs:
                # Duplicate edge — skip to avoid inflating in-degree
                continue
            seen_prereqs.add(prereq_id)
            node_id = _resolve_id(node, node_list)
            adjacency[prereq_id].append(node_id)
            in_degree[node_id] += 1

    # ------------------------------------------------------------------
    # Kahn's BFS
    # ------------------------------------------------------------------
    # Initial queue: all nodes with in-degree 0, sorted by key for determinism
    queue: deque[int] = deque(
        sorted(
            (nid for nid, deg in in_degree.items() if deg == 0),
            key=lambda nid: key(id_to_node[nid]),
        )
    )

    result: list[T] = []

    while queue:
        nid = queue.popleft()
        result.append(id_to_node[nid])

        # Collect newly-ready successors (in-degree drops to 0) then sort them
        # by key before adding to the deque so the overall ordering is stable.
        newly_ready: list[int] = []
        for successor_id in adjacency[nid]:
            in_degree[successor_id] -= 1
            if in_degree[successor_id] == 0:
                newly_ready.append(successor_id)

        newly_ready.sort(key=lambda nid: key(id_to_node[nid]))
        queue.extend(newly_ready)

    # ------------------------------------------------------------------
    # Cycle detection — any remaining non-zero in-degree node is in a cycle
    # ------------------------------------------------------------------
    if len(result) != len(node_list):
        cycle_members = sorted(
            (id_to_node[nid] for nid, deg in in_degree.items() if deg > 0),
            key=key,
        )
        members_repr = ", ".join(repr(m) for m in cycle_members)
        msg = (
            f"Dependency cycle detected among {len(cycle_members)} node(s): "
            f"{members_repr}.  "
            "Check the 'dependencies' mapping for circular prerequisites."
        )
        raise CyclicDependencyError(msg)

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_id[T](node: T, node_list: list[T]) -> int:
    """Return the ``id()`` of the canonical instance of *node* in *node_list*.

    Because caller code may pass prerequisite objects that are *equal* to but
    not *identical* to (different ``id()``) the objects in *node_list*, we
    resolve by identity first, then fall back to equality.

    Parameters
    ----------
    node:
        The node whose canonical ``id()`` we need.
    node_list:
        The authoritative list of all nodes, built from the *nodes* argument
        passed to :func:`topological_sort`.

    Returns
    -------
    int
        The ``id()`` of the matching object in *node_list*.
    """
    # Fast path: exact same object
    node_id = id(node)
    for n in node_list:
        if id(n) == node_id:
            return node_id
    # Slow path: equal but different object (e.g. two equal string literals)
    for n in node_list:
        if n == node:
            return id(n)
    # Should not reach here after validation — but be safe
    msg = f"Node {node!r} not found in node_list (internal error)."
    raise ValueError(msg)
