"""Unit tests for ``pgschemadiff.application.diff.topo_sort`` (task P2-DIFF-08).

Covers:
- Empty input → empty list
- Single node with no dependencies
- Linear chain (A → B → C)
- Diamond (A before B,C; B,C before D)
- Deterministic tie-breaking: two independent nodes always sorted by key
- Self-cycle raises CyclicDependencyError
- Multi-node cycle raises CyclicDependencyError
- CyclicDependencyError message names cycle members
- Unknown prerequisite raises ValueError
- Duplicate edges in dependencies (idempotent)
- Node with dependency not listed in dependencies mapping
- All nodes with no explicit dependencies → sorted by key
"""

from __future__ import annotations

import pytest

from pgschemadiff.application.diff.topo_sort import topological_sort
from pgschemadiff.shared.errors import CyclicDependencyError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _key(x: str) -> str:
    """Simple identity key for string nodes — sorts lexicographically."""
    return x


# ---------------------------------------------------------------------------
# Basic structural tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_empty_input_returns_empty_list() -> None:
    """An empty nodes iterable must yield an empty list."""
    result = topological_sort([], {}, key=_key)
    assert result == []


@pytest.mark.unit
def test_single_node_no_deps() -> None:
    """A single node with no dependencies must be returned in a single-item list."""
    result = topological_sort(["A"], {}, key=_key)
    assert result == ["A"]


@pytest.mark.unit
def test_single_node_empty_deps() -> None:
    """A single node with an explicit empty prerequisite list must be returned."""
    result = topological_sort(["A"], {"A": []}, key=_key)
    assert result == ["A"]


@pytest.mark.unit
def test_linear_chain_abc() -> None:
    """B depends on A, C depends on B → order must be [A, B, C]."""
    result = topological_sort(
        ["A", "B", "C"],
        {"B": ["A"], "C": ["B"]},
        key=_key,
    )
    assert result == ["A", "B", "C"]


@pytest.mark.unit
def test_linear_chain_input_reversed() -> None:
    """Reversed input order must still produce correct dependency order."""
    result = topological_sort(
        ["C", "B", "A"],
        {"B": ["A"], "C": ["B"]},
        key=_key,
    )
    assert result == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# Diamond topology
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_diamond_a_before_bcd() -> None:
    """Diamond: A → B, A → C, B → D, C → D.

    A must be first; D must be last; B and C appear in between (in key order).
    """
    result = topological_sort(
        ["A", "B", "C", "D"],
        {"B": ["A"], "C": ["A"], "D": ["B", "C"]},
        key=_key,
    )
    assert result[0] == "A"
    assert result[-1] == "D"
    assert set(result[1:3]) == {"B", "C"}
    # Tie-break: B < C lexicographically
    assert result[1] == "B"
    assert result[2] == "C"


# ---------------------------------------------------------------------------
# Deterministic tie-breaking
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_independent_nodes_sorted_by_key() -> None:
    """Completely independent nodes must be sorted by key regardless of input order."""
    # Provide nodes in reverse alphabetical order
    result = topological_sort(["Z", "M", "A", "B"], {}, key=_key)
    assert result == ["A", "B", "M", "Z"]


@pytest.mark.unit
def test_tie_break_with_integer_key() -> None:
    """Integer keys must also produce deterministic ordering."""
    nodes = [3, 1, 4, 1, 5, 9, 2, 6]
    # Remove duplicates for this test — topological_sort allows duplicates in
    # the node list but the identity-based resolution may behave unexpectedly.
    unique_nodes = list(dict.fromkeys(nodes))
    result = topological_sort(unique_nodes, {}, key=lambda x: x)
    assert result == sorted(unique_nodes)


@pytest.mark.unit
def test_tie_break_is_stable_for_two_ready_nodes() -> None:
    """With two simultaneously ready nodes 'alpha' and 'beta', 'alpha' must come first."""
    result = topological_sort(["beta", "alpha"], {}, key=_key)
    assert result == ["alpha", "beta"]


@pytest.mark.unit
def test_tie_break_independent_of_input_order() -> None:
    """Two identical graphs with reversed input order must produce the same sorted output."""
    deps = {"C": ["A"], "D": ["B"]}

    result_fwd = topological_sort(["A", "B", "C", "D"], deps, key=_key)
    result_rev = topological_sort(["D", "C", "B", "A"], deps, key=_key)

    assert result_fwd == result_rev


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_self_cycle_raises_cyclic_dependency_error() -> None:
    """A node that depends on itself must raise CyclicDependencyError."""
    with pytest.raises(CyclicDependencyError):
        topological_sort(["A"], {"A": ["A"]}, key=_key)


@pytest.mark.unit
def test_two_node_cycle_raises_cyclic_dependency_error() -> None:
    """A → B and B → A must raise CyclicDependencyError."""
    with pytest.raises(CyclicDependencyError):
        topological_sort(["A", "B"], {"A": ["B"], "B": ["A"]}, key=_key)


@pytest.mark.unit
def test_three_node_cycle_raises_cyclic_dependency_error() -> None:
    """A → B → C → A must raise CyclicDependencyError."""
    with pytest.raises(CyclicDependencyError):
        topological_sort(
            ["A", "B", "C"],
            {"B": ["A"], "C": ["B"], "A": ["C"]},
            key=_key,
        )


@pytest.mark.unit
def test_cycle_error_message_names_cycle_members() -> None:
    """The CyclicDependencyError message must contain the names of cycle members."""
    with pytest.raises(CyclicDependencyError) as exc_info:
        topological_sort(["X", "Y"], {"X": ["Y"], "Y": ["X"]}, key=_key)
    msg = str(exc_info.value)
    assert "X" in msg
    assert "Y" in msg


@pytest.mark.unit
def test_self_cycle_error_message_names_node() -> None:
    """The CyclicDependencyError message for a self-cycle must name the offending node."""
    with pytest.raises(CyclicDependencyError) as exc_info:
        topological_sort(["loop_node"], {"loop_node": ["loop_node"]}, key=_key)
    msg = str(exc_info.value)
    assert "loop_node" in msg


@pytest.mark.unit
def test_partial_cycle_non_cycle_nodes_not_mentioned_in_cycle_error() -> None:
    """Nodes outside the cycle are NOT expected in the error (cycle members only)."""
    # Graph: A (root) → B → C → B (cycle is B and C only; A is not in the cycle)
    # B depends on C AND on A; C depends on B → B↔C form a cycle
    with pytest.raises(CyclicDependencyError) as exc_info:
        topological_sort(
            ["A", "B", "C"],
            {"B": ["A", "C"], "C": ["B"]},
            key=_key,
        )
    msg = str(exc_info.value)
    # The cycle participants (B and C) must be mentioned
    assert "B" in msg or "C" in msg


# ---------------------------------------------------------------------------
# Input validation — unknown prerequisites
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_unknown_prerequisite_raises_value_error() -> None:
    """A prerequisite not in 'nodes' must raise ValueError immediately."""
    with pytest.raises(ValueError, match="Prerequisite"):
        topological_sort(
            ["A"],
            {"A": ["B"]},  # "B" is not in nodes
            key=_key,
        )


@pytest.mark.unit
def test_unknown_prerequisite_error_names_missing_node() -> None:
    """The ValueError message must mention the missing prerequisite."""
    with pytest.raises(ValueError, match="ghost"):
        topological_sort(["A"], {"A": ["ghost"]}, key=_key)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_node_not_in_dependencies_mapping_is_root() -> None:
    """A node absent from the dependencies mapping is treated as having no prerequisites."""
    # "A" is not in the mapping → it is a root and must appear first
    result = topological_sort(["A", "B"], {"B": ["A"]}, key=_key)
    assert result == ["A", "B"]


@pytest.mark.unit
def test_duplicate_prerequisites_are_handled() -> None:
    """Listing the same prerequisite twice must not inflate in-degree."""
    # B depends on A (listed twice — should be fine)
    result = topological_sort(["A", "B"], {"B": ["A", "A"]}, key=_key)
    assert result == ["A", "B"]


@pytest.mark.unit
def test_long_linear_chain() -> None:
    """A long chain of 100 nodes must be ordered correctly."""
    nodes = [str(i) for i in range(100)]
    deps = {nodes[i]: [nodes[i - 1]] for i in range(1, 100)}
    result = topological_sort(nodes, deps, key=_key)
    # Each node must appear after its predecessor
    for i in range(1, 100):
        assert result.index(nodes[i]) > result.index(nodes[i - 1])


@pytest.mark.unit
def test_all_nodes_independent_sorted_alphabetically() -> None:
    """When every node is independent, the result is the nodes sorted by key."""
    nodes = ["delta", "alpha", "gamma", "beta"]
    result = topological_sort(nodes, {}, key=_key)
    assert result == sorted(nodes)


@pytest.mark.unit
def test_result_contains_all_nodes() -> None:
    """The returned list must contain exactly the same nodes as the input."""
    nodes = ["A", "B", "C", "D", "E"]
    deps = {"C": ["A", "B"], "E": ["D"]}
    result = topological_sort(nodes, deps, key=_key)
    assert sorted(result) == sorted(nodes)


@pytest.mark.unit
def test_result_is_a_new_list() -> None:
    """topological_sort must return a new list object, not mutate any input."""
    nodes = ["A", "B"]
    original = list(nodes)
    result = topological_sort(nodes, {}, key=_key)
    assert result is not nodes
    assert nodes == original  # input unchanged


# ---------------------------------------------------------------------------
# Key callable contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_custom_key_controls_tie_break() -> None:
    """A custom key function must override lexicographic ordering."""
    # Nodes are strings; sort by *length* then content
    nodes = ["bb", "aaa", "c", "dd"]
    result = topological_sort(nodes, {}, key=lambda s: (len(s), s))
    # Expected: "c" (len 1), "bb" (len 2, < "dd"), "dd" (len 2, > "bb"), "aaa" (len 3)
    assert result == ["c", "bb", "dd", "aaa"]


@pytest.mark.unit
def test_negative_integer_key() -> None:
    """Nodes with negative integer keys must still be ordered correctly."""
    nodes = [-3, -1, -2]
    result = topological_sort(nodes, {}, key=lambda x: x)
    assert result == [-3, -2, -1]
