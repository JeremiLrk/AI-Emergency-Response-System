"""Handwritten uniform-cost graph search; course search slides pp. 44-47.

Costs must remain fixed throughout a search. Build a new snapshot when beliefs
change. Optimality applies to these supplied costs, not unknown true conditions.
"""
from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from math import isfinite

from .graph import Graph


@dataclass(frozen=True)
class Route:
    """A selected path and its total cost under one fixed planning snapshot.

    nodes includes both endpoints. roads[k] identifies the edge from nodes[k] to
    nodes[k+1], so len(roads) = len(nodes)-1. seconds is accumulated travel time;
    it excludes dispatch waiting and service duration and is not an absolute arrival.

    Parameters:
        nodes: Ordered tuple of visited node IDs, including both endpoints.
        roads: Ordered tuple of selected edge IDs; roads[k] connects nodes[k] to
            nodes[k+1].
        seconds: Total travel duration in seconds; excludes waiting/service and is not
            absolute arrival time.

    Preconditions:
        Direct callers must supply a consistent path/cost; the generated dataclass
        constructor does not validate it. ucs constructs routes according to its own
        contract.

    Postconditions:
        Creates a frozen record holding the values. Construction does not verify graph
        adjacency or perform dispatch.
    """
    nodes: tuple[str, ...]
    roads: tuple[str, ...]
    seconds: float


def ucs(graph: Graph, start: str, goal: str) -> Route | None:
    """Find a minimum-travel-time route using uniform-cost graph search.

    Returns:
        Route with both endpoints, selected road IDs and total travel seconds.
        Returns None if unreachable; start == goal yields a zero-cost one-node route.

    Raises:
        ValueError: Either endpoint is absent, or an explored travel sum overflows.

    The course's UCS frontier priority is cumulative cost g(n), with no heuristic.
    best stores cheapest discovered costs; parent stores the predecessor and road
    for reconstruction. Heap entries can become outdated when a cheaper path is
    found, so stale entries are skipped instead of needing a decrease-key operation.
    Optimality is relative to the supplied costs, not unknown actual road conditions.

    Parameters:
        graph: Finite initialized Graph with fixed nonnegative edge durations in
            seconds.
        start: Existing departure node ID.
        goal: Existing destination node ID.

    Preconditions:
        start and goal must exist (checked; otherwise ValueError). Caller must not
        mutate the graph during search. All explored accumulated costs must remain
        finite/representable; individual finite edges alone cannot prevent floating-
        point overflow. Costs are interpreted using Python floating-point arithmetic.

    Postconditions:
        Returns a minimum-cost Route for the fixed snapshot, or None if no directed
        path exists, under these assumptions. Route nodes start/end at start/goal,
        roads identify consecutive arcs, and seconds is their accumulated duration.
        start == goal returns one node, no roads, and zero seconds. The graph is
        unchanged.
    """
    if start not in graph or goal not in graph:
        raise ValueError("Start and goal must be graph nodes")
    # A counter breaks equal-cost heap ties in discovery order, without ranking IDs.
    serial = count()
    frontier = [(0.0, next(serial), start)]
    # Start with one empty path. Unknown nodes have an implicit infinite best cost.
    best = {start: 0.0}
    parent = {}
    while frontier:
        cost, _, node = heappop(frontier)
        if cost != best[node]:  # A better entry was queued after this one.
            continue
        # A discovered goal may still have a cheaper path waiting in the heap.
        if node == goal:  # Test on removal, never on first discovery.
            # Follow predecessor links backwards, then reverse for source-to-goal output.
            nodes, roads = [goal], []
            while node != start:
                node, road = parent[node]
                nodes.append(node)
                roads.append(road)
            return Route(tuple(reversed(nodes)), tuple(reversed(roads)), cost)
        # Relax each outgoing arc: keep only a strictly better cumulative cost.
        for edge in graph.neighbors(node):
            candidate = cost + edge.seconds
            if not isfinite(candidate):
                raise ValueError("Route travel time overflow")
            # Strict < also prevents equal-cost cycles from being re-enqueued forever.
            if candidate < best.get(edge.target, float("inf")):
                best[edge.target] = candidate
                parent[edge.target] = (node, edge.road_id)
                heappush(frontier, (candidate, next(serial), edge.target))
    # Exhausting the frontier proves no directed path exists in this snapshot.
    return None
