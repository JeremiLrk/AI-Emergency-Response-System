"""An explicit routing policy over full Bayesian marginal distributions.

Inference is in bayesian.py. This policy filters on per-edge blockage probability
and minimizes conditional travel time with ordinary UCS. It does not solve a
route-level chance constraint and does not certify safety or actual deadlines.
"""
from collections.abc import Mapping
from dataclasses import dataclass
from math import fsum, isclose, isfinite

from .graph import Graph
from .models import ROAD_STATUSES, Scenario
from .search import Route


def _validate_beliefs(scenario, beliefs):
    """Check full coverage and normalized distributions without modifying inputs.

    Parameters:
        scenario: Validated Scenario whose road keys define required coverage.
        beliefs: Mapping (from,to) -> mapping Open/Congested/Blocked -> probability.
    Preconditions:
        scenario is validated; belief keys must be hashable endpoint pairs.
    Postconditions:
        Returns None if every road has exactly one valid distribution. Does not
        renormalize. Invalid coverage, labels, ranges or sums raise ValueError.
    """
    if not isinstance(beliefs, Mapping) or set(beliefs) != {r.key for r in scenario.roads}:
        raise ValueError("Beliefs must cover exactly all directed scenario roads")
    for road, row in beliefs.items():
        if not isinstance(row, Mapping) or set(row) != ROAD_STATUSES:
            raise ValueError(f"Invalid probability labels on {road}")
        for value in row.values():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Non-numeric probability on {road}")
            if not isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"Probability outside [0,1] on {road}")
        if not isclose(fsum(row.values()), 1.0, rel_tol=0, abs_tol=1e-9):
            raise ValueError(f"Probabilities do not sum to one on {road}")


def build_bayesian_graph(scenario: Scenario, beliefs, *, blocked_threshold):
    """Construct a fixed UCS graph without collapsing posteriors to MAP labels.

    Parameters:
        scenario: Validated scenario with road lengths/speeds in metres/metres/sec.
        beliefs: Full status distributions keyed by directed endpoints.
        blocked_threshold: Explicit finite number in [0,1]. Keep only roads with
            P(Blocked) strictly less than this value. Zero excludes every road;
            one excludes certain blockages only. No default is hidden in this API.

    Preconditions:
        Complete normalized beliefs and the threshold are checked. Caller must
        keep inputs fixed. Choosing the threshold is a policy decision, not an
        inference result. Computed edge times must remain finite (Graph checks).

    Postconditions:
        Returns a new directed Graph containing every node. Accepted edges have
        cost t0 * (P(Open)+1.5*P(Congested))/(P(Open)+P(Congested)), in seconds.
        This is expected time conditional on that edge being traversable. Rejected
        edges are absent. Inputs and full beliefs are unchanged. Under correlated
        road statuses, the sum of edge-conditional means need not equal expected
        route time conditional on the entire route succeeding.

    Raises:
        ValueError: Invalid threshold/beliefs or nonfinite edge costs.
    """
    _validate_beliefs(scenario, beliefs)
    if (isinstance(blocked_threshold, bool)
            or not isinstance(blocked_threshold, (int, float))
            or not isfinite(blocked_threshold) or not 0 <= blocked_threshold <= 1):
        raise ValueError("blocked_threshold must be a finite number in [0,1]")
    graph = Graph(node.id for node in scenario.nodes)
    for road in scenario.roads:
        row = beliefs[road.key]
        traversable = row["Open"] + row["Congested"]
        if row["Blocked"] >= blocked_threshold or traversable <= 0:
            continue
        # Dividing by non-blocked mass is essential: ignoring it understates time.
        multiplier = (row["Open"] + 1.5 * row["Congested"]) / traversable
        graph.add_edge(road.source, road.target, road.normal_seconds * multiplier, road.id)
    return graph


@dataclass(frozen=True)
class BlockageBounds:
    """Dependence-agnostic bounds for at least one blocked road on a route.

    Parameters:
        lower: Maximum marginal P(Blocked) among distinct used directed roads.
        upper: min(1, sum of those marginal probabilities), the union bound.
    Preconditions:
        Direct construction does not validate fields; use route_blockage_bounds
        for values calculated from checked distributions and route structure.
    Postconditions:
        Frozen numeric record. Bounds describe the supplied probability model,
        not calibration against real-world truth or the chance of missing a deadline.
    """
    lower: float
    upper: float


def route_blockage_bounds(scenario: Scenario, beliefs, route: Route):
    """Report route blockage bounds without assuming independent road failures.

    Parameters:
        scenario: Validated scenario defining directed road IDs/endpoints.
        beliefs: Complete per-road marginal status distributions.
        route: Route whose road IDs connect its consecutive node IDs. Travel time
            is not revalidated here; callers use UCS's result for the same snapshot.

    Preconditions:
        Complete beliefs, route shape, node IDs and directed arcs are checked.
        route must be a Route object, not None. Interpreting repeated visits to
        a road as one event assumes its status remains static during traversal.

    Postconditions:
        Returns BlockageBounds for the union of distinct road blockage events:
        max(p_i) <= P(any blocked) <= min(1,sum(p_i)). No cross-road independence
        assumption is required. A zero-edge route has both bounds zero. Inputs
        remain unchanged; no threshold or route-level risk cap is enforced here.

    Raises:
        ValueError: Beliefs or route structure are inconsistent with the scenario.
    """
    _validate_beliefs(scenario, beliefs)
    if not route.nodes or len(route.roads) != len(route.nodes) - 1:
        raise ValueError("Route must have one road per consecutive node pair")
    node_ids = {n.id for n in scenario.nodes}
    if any(node not in node_ids for node in route.nodes):
        raise ValueError("Route references an unknown node")
    roads = {r.id: r for r in scenario.roads}
    used = set()
    for source, target, road_id in zip(route.nodes, route.nodes[1:], route.roads):
        if road_id not in roads or roads[road_id].key != (source, target):
            raise ValueError("Route road IDs do not match directed consecutive nodes")
        used.add(roads[road_id].key)
    probabilities = [beliefs[key]["Blocked"] for key in used]
    return BlockageBounds(max(probabilities, default=0.0), min(1.0, fsum(probabilities)))
