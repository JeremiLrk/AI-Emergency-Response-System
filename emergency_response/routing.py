"""Construct fixed routing snapshots, without performing Bayesian inference."""
from .graph import Graph
from .models import ROAD_STATUSES, Scenario


def build_graph(scenario: Scenario, statuses=None) -> Graph:
    """No statuses means the explicit all-open, normal-speed baseline.

    Otherwise require one externally chosen status per directed road. Never
    interpret a noisy report as a true status or silently fill partial beliefs.
    """
    if statuses is not None:
        if set(statuses) != {road.key for road in scenario.roads}:
            raise ValueError("Status snapshot must cover exactly the scenario's directed roads")
        if any(status not in ROAD_STATUSES for status in statuses.values()):
            raise ValueError("Status must be Open, Congested or Blocked")
    graph = Graph(node.id for node in scenario.nodes)
    for road in scenario.roads:
        status = "Open" if statuses is None else statuses[road.key]
        if status == "Blocked":
            continue
        multiplier = 1.5 if status == "Congested" else 1.0
        graph.add_edge(road.source, road.target, road.normal_seconds * multiplier, road.id)
    return graph
