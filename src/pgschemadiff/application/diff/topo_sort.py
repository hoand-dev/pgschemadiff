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
* **Complexity** — O(n + m) time and space where *n* is the number of nodes and
  *m* is the total number of edges.  Nodes are used directly as dict keys
  (requires ``T`` to be hashable), eliminating the O(n·m) ``id()``-resolution
  loop of the previous implementation.

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


def topological_sort[T: object](
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
        is missing a :exc:`ValueError` is raised immediately.  Nodes must be
        hashable so they can serve as dict keys.
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
    # Materialise the node list and build an O(1) membership set.
    # Nodes must be hashable — used directly as dict keys (O(n+m) overall).
    node_list: list[T] = list(nodes)
    node_set: set[T] = set(node_list)

    # ------------------------------------------------------------------
    # Validate: every prerequisite must be a known node
    # ------------------------------------------------------------------
    for node, prereqs in dependencies.items():
        for prereq in prereqs:
            if prereq not in node_set:
                msg = (
                    f"Prerequisite {prereq!r} (required by {node!r}) "
                    "is not in the nodes iterable.  All prerequisites must "
                    "be members of 'nodes'."
                )
                raise ValueError(msg)

    # ------------------------------------------------------------------
    # Build adjacency list and in-degree table (Kahn's algorithm setup)
    # ------------------------------------------------------------------
    # adjacency[node] = list of nodes that DEPEND ON node
    #   (i.e. node is a prerequisite for them — the forward edge in the
    #    "comes before" graph)
    adjacency: dict[T, list[T]] = {n: [] for n in node_list}
    in_degree: dict[T, int] = dict.fromkeys(node_list, 0)

    for node, prereqs in dependencies.items():
        seen_prereqs: set[T] = set()
        for prereq in prereqs:
            if prereq in seen_prereqs:
                # Duplicate edge — skip to avoid inflating in-degree
                continue
            seen_prereqs.add(prereq)
            adjacency[prereq].append(node)
            in_degree[node] += 1

    # ------------------------------------------------------------------
    # Kahn's BFS
    # ------------------------------------------------------------------
    # Initial queue: all nodes with in-degree 0, sorted by key for determinism
    queue: deque[T] = deque(
        sorted(
            (n for n, deg in in_degree.items() if deg == 0),
            key=key,
        )
    )

    result: list[T] = []

    while queue:
        node = queue.popleft()
        result.append(node)

        # Collect newly-ready successors (in-degree drops to 0) then sort them
        # by key before adding to the deque so the overall ordering is stable.
        newly_ready: list[T] = []
        for successor in adjacency[node]:
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                newly_ready.append(successor)

        newly_ready.sort(key=key)
        queue.extend(newly_ready)

    # ------------------------------------------------------------------
    # Cycle detection — any remaining non-zero in-degree node is in a cycle
    # ------------------------------------------------------------------
    if len(result) != len(node_list):
        cycle_members = sorted(
            (n for n, deg in in_degree.items() if deg > 0),
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
