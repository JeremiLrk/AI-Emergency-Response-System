"""Construct fixed routing snapshots, without performing Bayesian inference."""
from .graph import Graph
from .models import ROAD_STATUSES, Scenario


def build_graph(scenario: Scenario, statuses=None) -> Graph:
    """Convert validated roads into a fixed travel-time graph for search.

    Returns:
        A new directed Graph: Open uses normal time, Congested uses 1.5 times normal
        time, and Blocked edges are absent. Source scenario records are unchanged.

    Raises:
        ValueError: Status coverage or a status label is invalid.

    No Bayesian inference or HMM filtering occurs here. Callers must
    choose statuses before calling this explicit-label adapter. The probability-
    preserving Bayesian path uses risk_routing.build_bayesian_graph instead. Noisy reports are not truth,
    and missing entries are not silently filled when a status mapping is supplied.

    Parameters:
        scenario: Scenario with validated node IDs and directed Road records; normally
            returned by load_scenario.
        statuses: None for the all-open baseline, or a mapping (source, target) ->
            Open/Congested/Blocked covering exactly all roads.

    Preconditions:
        Caller supplies an unmodified validated scenario and does not change statuses
        during construction. If provided, exact status coverage and labels are checked.
        Computed times must remain finite; Graph.add_edge checks this for included
        arcs.

    Postconditions:
        Returns a new Graph containing every scenario node and exactly the non-Blocked
        directed arcs. Open costs distance/speed; Congested costs 1.5 times that; None
        means all Open. Scenario and mapping are unchanged. No report inference or
        traffic filtering is performed.
    """
    # Require complete explicit beliefs so missing roads cannot become Open by accident.
    if statuses is not None:
        if set(statuses) != {road.key for road in scenario.roads}:
            raise ValueError("Status snapshot must cover exactly the scenario's directed roads")
        if any(status not in ROAD_STATUSES for status in statuses.values()):
            raise ValueError("Status must be Open, Congested or Blocked")
    graph = Graph(node.id for node in scenario.nodes)
    for road in scenario.roads:
        status = "Open" if statuses is None else statuses[road.key]
        # Omit impassable arcs; zero time would incorrectly make them attractive.
        if status == "Blocked":
            continue
        multiplier = 1.5 if status == "Congested" else 1.0
        graph.add_edge(road.source, road.target, road.normal_seconds * multiplier, road.id)
    return graph
