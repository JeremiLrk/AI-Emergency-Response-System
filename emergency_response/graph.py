"""A directed graph whose edge costs are explicit travel times in seconds.

Convert source distances/speeds only after their units have been verified.
Undirected source roads must be added in both directions by the future adapter.
"""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class Edge:
    road_id: str
    target: str
    seconds: float


class Graph:
    def __init__(self, nodes):
        nodes = tuple(nodes)
        if any(not isinstance(n, str) or not n for n in nodes):
            raise ValueError("Node IDs must be nonempty strings")
        if len(set(nodes)) != len(nodes):
            raise ValueError("Duplicate node IDs")
        self._adj = {node: [] for node in nodes}

    def __contains__(self, node):
        return node in self._adj

    def add_edge(self, source, target, seconds, road_id):
        if source not in self or target not in self:
            raise ValueError("Edge endpoint is not in graph")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ValueError("Travel time must be numeric")
        if not isfinite(seconds) or seconds < 0:
            raise ValueError("Travel time must be finite and nonnegative")
        if not isinstance(road_id, str) or not road_id:
            raise ValueError("Road ID must be a nonempty string")
        self._adj[source].append(Edge(road_id, target, float(seconds)))

    def neighbors(self, node):
        return tuple(self._adj[node])
