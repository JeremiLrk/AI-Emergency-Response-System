"""UCS and A* graph search, following the course search methods.

Costs must remain fixed throughout a search. Build a new snapshot when beliefs
change. Optimality applies to these supplied costs, not unknown true conditions.
"""
from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from math import hypot, isfinite

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



def astar(graph: Graph, start: str, goal: str, heuristic) -> Route | None:
    """Find a minimum-time route with A*: frontier priority f(n) = g(n) + h(n).

    Parameters:
        graph: Finite directed Graph with fixed nonnegative travel seconds.
        start/goal: Existing departure and destination node IDs.
        heuristic: Callable(node) giving a lower bound on remaining travel seconds
            to this goal. Use straight_line_heuristic for checked scenario graphs.
    Preconditions:
        Graph and heuristic remain fixed. Caller must ensure h never overestimates
        true remaining cost; arbitrary callbacks cannot be proved admissible here.
        Values must be finite and nonnegative, with h(goal)=0 (checked when used).
        A consistent heuristic satisfies h(u) <= edge_seconds + h(v). Reopening
        improved nodes also supports admissible but inconsistent heuristics.
    Postconditions:
        Returns a minimum-cost Route, or None if unreachable, under these assumptions.
        start==goal returns one node and zero seconds. Graph is unchanged. Equal-cost
        paths may differ from UCS; actual accumulated seconds, never f, are returned.
    Raises:
        ValueError for missing endpoints, invalid heuristic values, or cost/priority
        overflow. Callback exceptions propagate. No simulator policy is changed.
    """
    if start not in graph or goal not in graph:
        raise ValueError("Start and goal must be graph nodes")
    if not callable(heuristic):
        raise ValueError("heuristic must be callable")
    estimates = {}

    def estimate(node):
        # Cache fixed estimates: repeated improvements must use the same h value.
        if node not in estimates:
            value = heuristic(node)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not isfinite(value) or value < 0 or (node == goal and value != 0)):
                raise ValueError("Heuristic must be finite, nonnegative, and zero at goal")
            estimates[node] = float(value)
        return estimates[node]

    estimate(goal)
    serial = count()
    frontier = [(estimate(start), next(serial), 0.0, start)]
    best = {start: 0.0}
    parent = {}
    while frontier:
        _, _, cost, node = heappop(frontier)
        if cost != best[node]:
            continue  # Discard a queued path replaced by a cheaper discovery.
        if node == goal:
            nodes, roads = [node], []
            while node != start:
                node, road = parent[node]
                nodes.append(node)
                roads.append(road)
            return Route(tuple(reversed(nodes)), tuple(reversed(roads)), cost)
        for edge in graph.neighbors(node):
            candidate = cost + edge.seconds
            if not isfinite(candidate):
                raise ValueError("Route travel time overflow")
            if candidate < best.get(edge.target, float("inf")):
                priority = candidate + estimate(edge.target)
                if not isfinite(priority):
                    raise ValueError("A* priority overflow")
                best[edge.target] = candidate
                parent[edge.target] = (node, edge.road_id)
                # No permanent closed set: a cheaper path reopens a visited node.
                heappush(frontier, (priority, next(serial), candidate, edge.target))
    return None


def straight_line_heuristic(scenario, graph: Graph, goal: str):
    """Build h(node) = straight-line metres to goal / maximum road speed.

    Parameters:
        scenario: Validated Scenario supplying coordinates, roads and speeds.
        graph: All-open or Bayesian graph made from these directed scenario roads.
        goal: Destination node ID in both inputs.
    Preconditions:
        Inputs stay fixed during construction. Coordinates are metres. Checks below
        reject roads shorter than their straight-line distance and graph edges faster
        than their normal road time, including invented road IDs/endpoints.
    Postconditions:
        Returns a fixed callable with a finite nonnegative estimate for every node,
        and zero at goal. The triangle inequality and maximum speed make h consistent
        (up to floating-point rounding), hence admissible. Congestion increases costs
        and filtering removes edges, so neither invalidates this lower bound.
        No routes are searched. An empty road set safely gives h=0.
    Raises:
        ValueError if the supplied graph/geometry cannot justify this heuristic.
    """
    nodes = {n.id: n for n in scenario.nodes}
    if goal not in nodes or goal not in graph:
        raise ValueError("Goal must be a scenario and graph node")
    if any(n.id not in graph or not isfinite(n.x) or not isfinite(n.y)
           for n in scenario.nodes):
        raise ValueError("Expected graph nodes with finite scenario coordinates")
    roads = {r.id: r for r in scenario.roads}
    for road in scenario.roads:
        a, b = nodes[road.source], nodes[road.target]
        if (not isfinite(road.speed) or road.speed <= 0 or
                not isfinite(road.distance) or
                road.distance < hypot(a.x-b.x, a.y-b.y)):
            raise ValueError("Road geometry/speed does not justify straight-line heuristic")
    for source in nodes:
        for edge in graph.neighbors(source):
            road = roads.get(edge.road_id)
            if (road is None or road.key != (source, edge.target)
                    or edge.seconds < road.normal_seconds):
                raise ValueError("Graph edge must match a road and cost at least normal time")
    maximum_speed = max((r.speed for r in scenario.roads), default=1.0)
    target = nodes[goal]
    estimates = {n.id: hypot(n.x-target.x, n.y-target.y)/maximum_speed
                 for n in scenario.nodes}
    if any(not isfinite(value) for value in estimates.values()):
        raise ValueError("Heuristic distance overflow")
    return estimates.__getitem__
