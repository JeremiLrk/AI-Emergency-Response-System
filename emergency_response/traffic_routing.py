"""Historical traffic as a separate route criterion, never an edge-time multiplier.

Q(path)=sum_e normal_seconds(e)*P(High_e | historical observations).
Exact policy minimizes (Bayesian time,Q); bounded policy minimizes (Q,time)
subject to a configured time bound and required exposure reduction. All edge
seconds and Route.seconds retain their original Bayesian travel interpretation.
"""
from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from math import isclose, isfinite, fsum

from .hmm import STATES
from .search import Route


class TrafficSearchLimit(ValueError):
    """Bounded-label resource guard; never silently claim an unproven route optimum.

    Parameters: explanatory exception message.
    Preconditions: generated labels exceed the explicitly documented guard.
    Postconditions: caller sees a failed search rather than an invented no-route.
    """


@dataclass(frozen=True)
class RouteExposure:
    """A route's historical traffic score and time comparison with a shortest route.

    Parameters:
        exposure: Sum of normal road seconds times historical P(High), not travel.
        shortest_seconds: Minimum Bayesian travel duration for these endpoints.
        shortest_exposure: Lowest exposure among exact shortest-time routes.
        extra_seconds: Chosen Route.seconds minus minimum travel time.
        reduction_fraction: Relative exposure reduction from tie-optimal shortest,
            zero when shortest exposure is zero.
    Preconditions: built by TrafficRouter.describe using validated route metadata.
    Postconditions: frozen explanation; no guarantee of present traffic/safety.
    """
    exposure: float
    shortest_seconds: float
    shortest_exposure: float
    extra_seconds: float
    reduction_fraction: float


def _fraction(value, name):
    """Validate a finite fractional policy setting in [0,1].

    Parameters: value is numeric fraction; name labels validation errors.
    Preconditions: none; bool/non-numeric/range are checked.
    Postconditions: returns float or raises ValueError; no mutation.
    """
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not isfinite(value) or not 0 <= value <= 1):
        raise ValueError(f"{name} must be a finite fraction in [0,1]")
    return float(value)


class TrafficRouter:
    """An injectable route policy holding road metadata/traffic, never future incidents.

    Parameters: see __init__; roads and traffic beliefs are startup information.
    Preconditions: graph costs fixed/nonnegative, road identities unambiguous.
    Postconditions: returned Route.seconds always sums original graph edge seconds.
        No multiplication/max of slowdown factors, probability fusion or CSP change.
    """

    def __init__(self, roads, beliefs, *, policy="tie", max_extra_fraction=0.0,
                 min_exposure_reduction=0.10, label_limit=100000):
        """Copy independent exposure weights and configure a fixed routing preference.

        Parameters:
            self: New router receiver.
            roads: Directed Road records only, not Scenario/incident information.
            beliefs: Complete directed-key -> TrafficBelief map from infer_traffic.
            policy: tie for exact (time,exposure) optimization; bounded for lowest
                exposure within (1+max_extra_fraction)*shortest time.
            max_extra_fraction: Fraction in [0,1], normally a small explicit value;
                used only in bounded mode. Evaluation fixes .05 before seeing results.
            min_exposure_reduction: Required fractional improvement over tie-optimal
                shortest exposure before accepting a slower route; evaluation .10.
            label_limit: Positive integer guard on generated bounded-search labels.
        Preconditions: full belief coverage/labels/ranges/sums, road IDs/cost metadata
            and policy settings checked. Nested inputs are copied/read, not modified.
        Postconditions: stores numeric exposure weights only; no future work, graph
            time changes or learned/tuned parameters. No physical traffic interval
            or road-time multipliers are invented.
        """
        if policy not in {"tie", "bounded"}:
            raise ValueError("Traffic policy must be tie or bounded")
        if isinstance(label_limit, bool) or not isinstance(label_limit, int) or label_limit < 1:
            raise ValueError("label_limit must be a positive integer")
        self.policy = policy
        self.max_extra_fraction = _fraction(max_extra_fraction, "max_extra_fraction")
        self.min_exposure_reduction = _fraction(min_exposure_reduction, "min_exposure_reduction")
        self.label_limit = label_limit
        roads = tuple(roads)
        self._roads = {r.id: r for r in roads}
        if len(self._roads) != len(roads) or len({r.key for r in roads}) != len(roads):
            raise ValueError("Road IDs and directed keys must be unique")
        if set(beliefs) != {r.key for r in roads}:
            raise ValueError("Traffic beliefs must cover exactly all directed roads")
        self._exposure = {}
        for road in roads:
            row = beliefs[road.key].probabilities
            if set(row) != set(STATES):
                raise ValueError("Invalid traffic probability labels")
            for value in row.values():
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not isfinite(value) or not 0 <= value <= 1):
                    raise ValueError("Invalid traffic probability range")
            if not isclose(fsum(row.values()), 1, rel_tol=0, abs_tol=1e-9):
                raise ValueError("Traffic probabilities must sum to one")
            if (not isfinite(road.distance) or road.distance < 0
                    or not isfinite(road.speed) or road.speed <= 0
                    or not isfinite(road.normal_seconds)):
                raise ValueError("Invalid normal road time metadata")
            self._exposure[road.id] = road.normal_seconds*row["High"]

    def _check_graph(self, graph, start, goal):
        """Check endpoint presence and reachable graph-edge metadata.

        Parameters: self is router; graph is fixed graph; start/goal are node IDs.
        Preconditions: Graph enforces finite nonnegative edge times on insertion.
        Postconditions: returns None or raises ValueError on unknown road identities;
            only reachable arcs are inspected, with no graph mutation.
        """
        if start not in graph or goal not in graph:
            raise ValueError("Start and goal must be graph nodes")
        seen, stack = set(), [start]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            for edge in graph.neighbors(node):
                road = self._roads.get(edge.road_id)
                if road is None or road.key != (node, edge.target):
                    raise ValueError("Graph arc does not match directed traffic metadata")
                stack.append(edge.target)

    def exposure(self, route):
        """Calculate separate reference-time-weighted historical High exposure.

        Parameters: self is router; route is a Route with known directed road IDs.
        Preconditions: route shape/endpoints/road metadata checked here. Travel cost
            itself is validated by search/controller, not replaced by this score.
        Postconditions: returns nonnegative score, zero for no roads. A road repeated
            during a traversal contributes again (exposure is additive traversal,
            unlike the distinct-road blockage union bound). Inputs unchanged.
        """
        if not route.nodes or len(route.roads) != len(route.nodes)-1:
            raise ValueError("Invalid traffic route shape")
        total = 0.0
        for a, b, road_id in zip(route.nodes, route.nodes[1:], route.roads):
            if road_id not in self._roads or self._roads[road_id].key != (a, b):
                raise ValueError("Route does not match directed traffic metadata")
            total += self._exposure[road_id]
        return total

    def _shortest(self, graph, start, goal):
        """Handwritten lexicographic UCS: primary original time, secondary exposure.

        Parameters: self supplies exposure; graph/start/goal already checked.
        Preconditions: fixed finite nonnegative time/exposure weights.
        Postconditions: minimum (time,exposure) Route, or None when disconnected.
            Exact float comparisons only; no epsilon manufactures equal-time ties.
            Route.seconds is time, never the secondary score.
        """
        serial = count()
        queue = [(0.0, 0.0, next(serial), start)]
        best, parent = {start: (0.0, 0.0)}, {}
        while queue:
            time, score, _, node = heappop(queue)
            if best[node] != (time, score):
                continue
            if node == goal:
                nodes, roads = [goal], []
                while node != start:
                    node, road = parent[node]
                    nodes.append(node)
                    roads.append(road)
                return Route(tuple(reversed(nodes)), tuple(reversed(roads)), time)
            for edge in graph.neighbors(node):
                cost = time+edge.seconds, score+self._exposure[edge.road_id]
                if not all(isfinite(v) for v in cost):
                    raise ValueError("Traffic route accumulation overflow")
                if cost < best.get(edge.target, (float("inf"), float("inf"))):
                    best[edge.target] = cost
                    parent[edge.target] = node, edge.road_id
                    heappush(queue, (*cost, next(serial), edge.target))
        return None

    def _bounded(self, graph, start, goal, cap):
        """Find lowest (exposure,time) walk under a time resource bound with Pareto labels.

        Parameters: self is router; graph/start/goal validated; cap is finite seconds.
        Preconditions: all costs nonnegative; graph fixed. Time is NOT an objective
            penalty merged into exposure. Dominance requires <= time AND <= exposure.
        Postconditions: returns optimal resource-feasible Route or None. Multiple
            labels per node preserve slower/cleaner prefixes that scalar UCS would
            discard. Dominated/identical labels suppress nonnegative cycles. General
            constrained shortest paths can need exponentially many labels; exceeding
            label_limit raises TrafficSearchLimit, not a silent approximate optimum.
        """
        # Each immutable label is (node,time,exposure,parent_label,road_id).
        labels = [(start, 0.0, 0.0, None, None)]
        active = {0}
        at_node = {start: [0]}
        queue = [(0.0, 0.0, 0)]
        while queue:
            _, _, index = heappop(queue)
            if index not in active:
                continue
            node, time, score, _, _ = labels[index]
            if node == goal:
                nodes, roads, position = [], [], index
                while position is not None:
                    n, _, _, previous, road = labels[position]
                    nodes.append(n)
                    if road is not None:
                        roads.append(road)
                    position = previous
                return Route(tuple(reversed(nodes)), tuple(reversed(roads)), time)
            for edge in graph.neighbors(node):
                next_time = time+edge.seconds
                next_score = score+self._exposure[edge.road_id]
                if not isfinite(next_time) or not isfinite(next_score):
                    raise ValueError("Traffic route accumulation overflow")
                if next_time > cap:
                    continue
                previous_labels = [k for k in at_node.get(edge.target, ()) if k in active]
                if any(labels[k][1] <= next_time and labels[k][2] <= next_score for k in previous_labels):
                    continue
                for k in previous_labels:
                    if next_time <= labels[k][1] and next_score <= labels[k][2]:
                        active.remove(k)
                if len(labels) >= self.label_limit:
                    raise TrafficSearchLimit("Bounded traffic search exceeded label_limit; no optimum returned")
                new_index = len(labels)
                labels.append((edge.target, next_time, next_score, index, edge.road_id))
                active.add(new_index)
                at_node.setdefault(edge.target, []).append(new_index)
                heappush(queue, (next_score, next_time, new_index))
        return None

    def __call__(self, graph, start, goal, *, max_seconds=None):
        """Select a route without changing edge times or consuming new observations.

        Parameters:
            self: Configured router.
            graph/start/goal: Fixed graph and current endpoint IDs.
            max_seconds: Optional remaining strict-arrival duration budget; None
                means no deadline cap. Bounded time cap is also <=(1+fraction)*T*.
        Preconditions: budget finite/nonnegative if supplied; metadata checked.
        Postconditions: returns Route or None if disconnected/budget-infeasible.
            Tie policy minimizes (T,Q). Bounded policy accepts a strictly slower
            route only for strictly lower Q AND at least the configured fractional
            reduction relative to the tie-optimal shortest route. Otherwise returns
            that shortest route. Zero exposure never induces gratuitous detours.
            Route.seconds remains the sum of unchanged Bayesian edge times.
        """
        self._check_graph(graph, start, goal)
        if max_seconds is not None and (isinstance(max_seconds, bool)
                or not isinstance(max_seconds, (int, float)) or not isfinite(max_seconds) or max_seconds < 0):
            raise ValueError("max_seconds must be finite nonnegative seconds")
        shortest = self._shortest(graph, start, goal)
        if shortest is None or (max_seconds is not None and shortest.seconds > max_seconds):
            return None
        if self.policy == "tie" or shortest.seconds == 0 or self.max_extra_fraction == 0:
            return shortest
        cap = shortest.seconds*(1+self.max_extra_fraction)
        if not isfinite(cap):
            raise ValueError("Bounded travel-time cap overflow")
        if max_seconds is not None:
            cap = min(cap, max_seconds)
        choice = self._bounded(graph, start, goal, cap)
        if choice is None:
            return shortest
        old, new = self.exposure(shortest), self.exposure(choice)
        if new < old and new <= old*(1-self.min_exposure_reduction):
            return choice
        return shortest

    def describe(self, graph, route):
        """Explain one committed route relative to the tie-optimal shortest alternative.

        Parameters: self is router; graph is the fixed snapshot; route is selected
            Route. Only endpoints/current historical information are used.
        Preconditions: route valid, reachable and based on this graph.
        Postconditions: RouteExposure explanation; neither route time nor graph
            changes. A positive extra_seconds reports an actual modeled detour.
        """
        self._check_graph(graph, route.nodes[0], route.nodes[-1])
        shortest = self._shortest(graph, route.nodes[0], route.nodes[-1])
        old, new = self.exposure(shortest), self.exposure(route)
        return RouteExposure(new, shortest.seconds, old, route.seconds-shortest.seconds,
                             (old-new)/old if old > 0 else 0.0)
