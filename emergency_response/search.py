"""Handwritten uniform-cost graph search; course search slides pp. 44-47.

Costs must remain fixed throughout a search. Build a new snapshot when beliefs
change. Optimality applies to these supplied costs, not unknown true conditions.
"""
from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count

from .graph import Graph


@dataclass(frozen=True)
class Route:
    nodes: tuple[str, ...]
    roads: tuple[str, ...]
    seconds: float


def ucs(graph: Graph, start: str, goal: str) -> Route | None:
    if start not in graph or goal not in graph:
        raise ValueError("Start and goal must be graph nodes")
    serial = count()
    frontier = [(0.0, next(serial), start)]
    best = {start: 0.0}
    parent = {}
    while frontier:
        cost, _, node = heappop(frontier)
        if cost != best[node]:  # A better entry was queued after this one.
            continue
        if node == goal:  # Test on removal, never on first discovery.
            nodes, roads = [goal], []
            while node != start:
                node, road = parent[node]
                nodes.append(node)
                roads.append(road)
            return Route(tuple(reversed(nodes)), tuple(reversed(roads)), cost)
        for edge in graph.neighbors(node):
            candidate = cost + edge.seconds
            if candidate < best.get(edge.target, float("inf")):
                best[edge.target] = candidate
                parent[edge.target] = (node, edge.road_id)
                heappush(frontier, (candidate, next(serial), edge.target))
    return None
