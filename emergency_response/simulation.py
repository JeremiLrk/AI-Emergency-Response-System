"""Discrete-event, deterministic execution of route estimates; no allocator/CSP.

A dispatcher receives only frozen views of revealed work and may propose an
immediate batch. The engine validates it independently and commits atomically.
All releases/completions/arrivals at a time are applied before a decision. New
zero-duration events are drained before deadline expiry at that same time.
"""
from dataclasses import dataclass, replace
from heapq import heappop, heappush
from itertools import count
from math import fsum, isfinite

from .graph import Graph
from .models import Scenario
from .search import ucs
from .simulation_models import (AssignmentRequest, AssignmentRecord, Candidate,
    DecisionSnapshot, IncidentView, ResponderView, SimulationEvent, SimulationResult)


def _time(value, name):
    """Validate one absolute time/duration, preserving fractional seconds.

    Parameters: value is a number to check; name labels errors.
    Preconditions: none beyond normal numeric input; bool/type/range are checked.
    Postconditions: returns a finite nonnegative float, or raises ValueError.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric seconds")
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return float(value)


def _add_time(start, duration):
    """Add modeled seconds, detecting overflow and unrepresentable positive advances.

    Parameters: start is current absolute time; duration is a nonnegative interval.
    Preconditions: both have passed _time; input precision is float precision.
    Postconditions: returns finite time >= start. A positive duration that cannot
        advance a large floating-point clock raises ValueError instead of acting zero.
    """
    try:
        result = fsum((start, duration))
    except OverflowError as error:
        raise ValueError("Simulation clock overflow") from error
    if not isfinite(result) or (duration > 0 and result <= start):
        raise ValueError("Simulation time advance is not representable")
    return result


@dataclass
class _ResponderState:
    """Private mutable state; never passed to a dispatcher.

    Parameters: view is an immutable current ResponderView; start is the supplied
        node assumed to be the completion position of an initially busy job.
    Preconditions: simulator constructs consistent state from validated input.
    Postconditions: engine can replace view without mutating earlier snapshots.
    """
    view: ResponderView
    start: str


class _Simulator:
    """Private single-run controller; use simulate() as the public entry point.

    Parameters: see __init__ and simulate for scenario, graph and policy arguments.
    Preconditions: initialize once, then call run once; no callback gets this object.
    Postconditions: state transitions and commitments are recorded in isolated state.
    """

    def __init__(self, scenario, graph, dispatcher, strict_deadlines, decision_times, route_planner=None):
        """Create isolated engine state and a private copy of the routing graph.

        Parameters:
            self: New engine receiver.
            scenario: Validated Scenario; future inputs stay inside this controller.
            graph: Fixed routing snapshot, possibly Bayesian-threshold filtered.
            dispatcher: Callable DecisionSnapshot -> iterable AssignmentRequest.
            strict_deadlines: bool; True forbids late dispatch and closes missed
                pending work, False leaves missed work eligible for later response.
            decision_times: Explicit optional wake-up times, unrelated to hidden input.
            route_planner: Optional callable(graph,start,goal,max_seconds=...);
                receives a strict arrival-duration budget, never future incidents.
        Preconditions: input IDs/field consistency follow load_scenario; duplicate
            entity IDs, graph coverage, time ranges and policy type are rechecked.
        Postconditions: initializes events at zero, releases, initial availability
            and explicit wake-ups; source inputs/graph are not changed.
        """
        if not isinstance(strict_deadlines, bool) or not callable(dispatcher):
            raise ValueError("Expected bool strict_deadlines and callable dispatcher")
        self.dispatcher = dispatcher
        if route_planner is not None and not callable(route_planner):
            raise ValueError("route_planner must be callable or None")
        self.route_planner = route_planner
        self.strict = strict_deadlines
        self.now = 0.0
        self.serial = count()
        self.queue = []
        self.log = []
        self.assignments = []
        self.revealed = {}
        self.inputs = {i.id: i for i in scenario.incidents}
        if len(self.inputs) != len(scenario.incidents):
            raise ValueError("Duplicate incident IDs")
        self.responders = {}
        nodes = {n.id for n in scenario.nodes}
        if len(nodes) != len(scenario.nodes) or any(n not in graph for n in nodes):
            raise ValueError("Routing graph must contain every unique scenario node")
        # Copy edges before the dispatcher can run: it receives neither graph nor Scenario.
        self.graph = Graph(nodes)
        for node in sorted(nodes):
            for edge in graph.neighbors(node):
                if edge.target not in nodes:
                    raise ValueError("Routing edge endpoint outside scenario")
                self.graph.add_edge(node, edge.target, edge.seconds, edge.road_id)
        self._schedule(0, "start", None)
        for responder in scenario.responders:
            if responder.id in self.responders or responder.start_location not in nodes:
                raise ValueError("Invalid responder ID/location")
            ready = _time(responder.time_until_available, "initial availability")
            if responder.availability not in {"Available", "Busy"}:
                raise ValueError("Unknown initial availability")
            if responder.availability == "Available" and ready != 0:
                raise ValueError("Available responder has nonzero initial busy time")
            busy = responder.availability == "Busy"
            view = ResponderView(responder.id, responder.capabilities,
                "initially_busy" if busy else "available",
                None if busy else responder.start_location, ready, None)
            self.responders[responder.id] = _ResponderState(view, responder.start_location)
            if busy:
                self._schedule(ready, "initial_available", responder.id)
        for incident in scenario.incidents:
            if incident.location not in nodes:
                raise ValueError("Incident location outside scenario")
            self._schedule(_time(incident.timestamp, "release"), "release", incident.id)
            _time(incident.deadline, "deadline")
            _time(incident.time_required, "treatment duration")
        for time in decision_times:
            self._schedule(_time(time, "decision wake-up"), "wake", None)

    def _schedule(self, time, kind, entity):
        """Queue a stable timestamped event without revealing it to dispatchers.

        Parameters: self is engine; time is absolute seconds; kind identifies an
            engine event; entity is an input ID, AssignmentRecord or None.
        Preconditions: time is finite and >= current clock; checked here.
        Postconditions: one heap entry added; ties use a monotone insertion counter.
        """
        time = _time(time, "event time")
        if time < self.now:
            raise ValueError("Cannot schedule an event in the past")
        heappush(self.queue, (time, next(self.serial), kind, entity))

    def _event(self, kind, responder=None, incident=None, message=""):
        """Append a processed event to the audit log.

        Parameters: self is engine; kind is log category; responder/incident are
            affected IDs or None; message is descriptive text.
        Preconditions: current clock and state transition are already valid.
        Postconditions: one immutable log record added at current time.
        """
        self.log.append(SimulationEvent(self.now, kind, responder, incident, message))

    def _apply(self, kind, entity):
        """Apply one non-deadline event, potentially scheduling immediate successors.

        Parameters: self is engine; kind/entity come from the private queue.
        Preconditions: all earlier times processed; deadline events are handled
            separately after same-time dispatch/zero-duration closure.
        Postconditions: updates revealed/operational state, never source records;
            arrival begins treatment, completion frees at the incident node.
        """
        if kind in {"start", "wake"}:
            return
        if kind == "release":
            incident = self.inputs[entity]
            self.revealed[entity] = IncidentView(incident, "pending", "not_due")
            self._event("release", incident=entity)
            # A strictly past deadline is already missed; unlike equality, no
            # same-time zero-travel assignment can rescue it before dispatch.
            if incident.deadline < self.now:
                self._deadline(entity)
            else:
                self._schedule(incident.deadline, "deadline", entity)
        elif kind == "initial_available":
            state = self.responders[entity]
            state.view = replace(state.view, status="available", location=state.start)
            self._event("initial_available", responder=entity)
        elif kind == "arrival":
            record = entity
            incident = self.revealed[record.incident_id]
            on_time = self.now <= incident.incident.deadline
            self.revealed[record.incident_id] = replace(incident, status="treating",
                deadline_result="met" if on_time else "missed", arrival_time=self.now)
            state = self.responders[record.responder_id]
            state.view = replace(state.view, status="treating", location=incident.incident.location)
            self._event("arrival", record.responder_id, record.incident_id)
            self._schedule(record.completion_time, "completion", record)
        elif kind == "completion":
            record = entity
            incident = self.revealed[record.incident_id]
            self.revealed[record.incident_id] = replace(incident, status="completed", completion_time=self.now)
            state = self.responders[record.responder_id]
            state.view = replace(state.view, status="available", incident_id=None,
                                 available_at=self.now)
            self._event("completion", record.responder_id, record.incident_id)
        else:
            raise ValueError(f"Unknown internal event: {kind}")

    def _snapshot(self):
        """Build an immutable current-time decision view and immediate UCS candidates.

        Parameters: self is initialized engine with all due state changes applied.
        Preconditions: source graph fixed; only revealed pending work is considered.
        Postconditions: returns no future incidents, event queue or engine reference.
            Candidates obey capabilities, availability, connectivity and selected
            deadline policy. Does not alter state or reserve a busy responder.
        """
        candidates = []
        responders = tuple(self.responders[key].view for key in sorted(self.responders))
        incidents = tuple(self.revealed[key] for key in sorted(self.revealed))
        for responder in responders:
            if responder.status != "available":
                continue
            for view in incidents:
                incident = view.incident
                if view.status != "pending" or incident.required_capability not in responder.capabilities:
                    continue
                if self.route_planner is None:
                    route = ucs(self.graph, responder.location, incident.location)
                else:
                    budget = max(0.0, incident.deadline-self.now) if self.strict else None
                    route = self.route_planner(self.graph, responder.location,
                                              incident.location, max_seconds=budget)
                    if route is not None:
                        self._check_route(route, responder.location, incident.location)
                    # Subtraction can round a duration budget below a feasible
                    # shortest path. The simulator's absolute arrival check wins.
                    if self.strict and (route is None or
                            _add_time(self.now, route.seconds) > incident.deadline):
                        route = ucs(self.graph, responder.location, incident.location)
                if route is None:
                    continue
                arrival = _add_time(self.now, route.seconds)
                on_time = arrival <= incident.deadline
                if self.strict and not on_time:
                    continue
                completion = _add_time(arrival, incident.time_required)
                candidates.append(Candidate(responder.id, incident.id, route, arrival, completion, on_time))
        return DecisionSnapshot(self.now, responders, incidents, tuple(candidates), self.strict)

    def _check_route(self, route, start, goal):
        """Check injected route duration against original graph costs.

        Parameters: route is a planner result; start/goal are candidate endpoints.
        Preconditions: fixed graph; road identifiers identify directed edges.
        Postconditions: returns None or raises ValueError for invented edges,
            endpoints or duration. Exposure can never substitute for travel time.
        """
        if (not route.nodes or route.nodes[0] != start or route.nodes[-1] != goal
                or len(route.nodes) != len(route.roads)+1):
            raise ValueError("Planner returned invalid route endpoints/shape")
        seconds = 0.0
        for a, b, road_id in zip(route.nodes, route.nodes[1:], route.roads):
            edges = [e for e in self.graph.neighbors(a) if e.target == b and e.road_id == road_id]
            if len(edges) != 1:
                raise ValueError("Planner returned unknown/ambiguous directed edge")
            seconds += edges[0].seconds
        if not isfinite(seconds) or route.seconds != seconds:
            raise ValueError("Planner duration must equal original graph travel seconds")

    def _dispatch(self, snapshot):
        """Validate a proposed batch completely before committing any assignment.

        Parameters: self is engine; snapshot is the current frozen decision state.
        Preconditions: dispatcher returns iterable AssignmentRequest, or raises.
        Postconditions: all valid requests commit at current time with frozen routes,
            travel state and arrival events. Invalid batches raise ValueError before
            any dispatch in that batch; earlier processed events are not rolled back.
        """
        requests = tuple(self.dispatcher(snapshot))
        eligible = {(c.responder_id, c.incident_id): c for c in snapshot.candidates}
        chosen, responders, incidents = [], set(), set()
        for request in requests:
            if not isinstance(request, AssignmentRequest):
                raise ValueError("Dispatcher must return AssignmentRequest objects")
            if any(not isinstance(value, str) or not value for value in
                   (request.responder_id, request.incident_id)):
                raise ValueError("Dispatch IDs must be nonempty strings")
            key = (request.responder_id, request.incident_id)
            if request.responder_id in responders or request.incident_id in incidents:
                raise ValueError("Dispatch batch repeats a responder or incident")
            if key not in eligible:
                raise ValueError(f"Ineligible dispatch at time {self.now}: {key}")
            responders.add(request.responder_id)
            incidents.add(request.incident_id)
            chosen.append(eligible[key])
        for candidate in chosen:
            record = AssignmentRecord(candidate.responder_id, candidate.incident_id,
                self.now, candidate.route, candidate.arrival_time, candidate.completion_time)
            self.assignments.append(record)
            state = self.responders[candidate.responder_id]
            state.view = replace(state.view, status="travelling", location=None,
                incident_id=candidate.incident_id, available_at=candidate.completion_time)
            self.revealed[candidate.incident_id] = replace(self.revealed[candidate.incident_id],
                status="travelling", responder_id=candidate.responder_id)
            self._event("dispatch", candidate.responder_id, candidate.incident_id)
            self._schedule(candidate.arrival_time, "arrival", record)

    def _deadline(self, incident_id):
        """Record a deadline miss independently, optionally closing pending work.

        Parameters: self is engine; incident_id identifies a revealed due incident.
        Preconditions: same-time arrivals and zero-duration dispatches have settled,
            or the deadline strictly precedes a just-revealed incident's release.
        Postconditions: no-arrival incidents become missed; strict pending ones
            close_unassigned. Late-enabled pending/travelling work remains active.
            Met incidents continue treatment without expiry or extra log events.
        """
        view = self.revealed[incident_id]
        if view.arrival_time is not None:
            return
        self.revealed[incident_id] = replace(view, deadline_result="missed")
        self._event("deadline_missed", incident=incident_id)
        if self.strict and view.status == "pending":
            self._close(incident_id, "strict_deadline_unassigned")

    def _close(self, incident_id, reason):
        """Close unassigned work without overwriting its deadline result.

        Parameters: self is engine; incident_id is pending; reason explains policy.
        Preconditions: pending status established by caller; no active job is closed.
        Postconditions: status becomes closed_unassigned; deadline_result is retained.
        """
        self.revealed[incident_id] = replace(self.revealed[incident_id],
            status="closed_unassigned", unassigned_reason=reason)
        self._event("closed_unassigned", incident=incident_id, message=reason)

    def run(self):
        """Drain event batches with same-time causal closure, then return final views.

        Parameters: self is initialized, not previously run engine.
        Preconditions: dispatcher must return promptly and not depend on hidden input.
        Postconditions: returns SimulationResult. Every source incident was revealed;
            all committed travel/treatment finishes. Pending allow-late work closes
            only when no events remain. Empty decisions never cause a busy loop.
        """
        while self.queue:
            # Completed/met incidents' obsolete deadline events do not extend horizon.
            time, _, kind, entity = self.queue[0]
            if kind == "deadline" and self.revealed[entity].deadline_result != "not_due":
                heappop(self.queue)
                continue
            self.now = time
            deadlines = set()
            while True:
                # This loop also drains arrival->completion chains of zero duration.
                while self.queue and self.queue[0][0] == self.now:
                    _, _, kind, entity = heappop(self.queue)
                    if kind == "deadline":
                        deadlines.add(entity)
                    else:
                        self._apply(kind, entity)
                snapshot = self._snapshot()
                self._dispatch(snapshot)
                if not self.queue or self.queue[0][0] != self.now:
                    break
                # A same-time dispatch requires real state progress: each job commits
                # once, so finite incidents imply this closure loop terminates.
            for incident_id in sorted(deadlines):
                if self.revealed[incident_id].deadline_result == "not_due":
                    self._deadline(incident_id)
        for incident_id, view in tuple(self.revealed.items()):
            if view.status == "pending":
                self._close(incident_id, "no_more_events_unassigned")
        final = self._snapshot()
        return SimulationResult(self.now, self.strict, tuple(self.assignments),
            final.responders, final.incidents, tuple(self.log))


def simulate(scenario: Scenario, graph: Graph, dispatcher, *, strict_deadlines=True,
             decision_times=(), route_planner=None):
    """Execute scripted/callback dispatches using deterministic route estimates.

    Parameters:
        scenario: Validated Scenario; original records remain unchanged.
        graph: Fixed routing snapshot, from baseline or Bayesian policy. Copied
            privately; its finite nonnegative costs become modeled travel durations.
        dispatcher: Callable taking only DecisionSnapshot and returning an iterable
            of AssignmentRequest. No CSP/greedy optimization is supplied here.
        strict_deadlines: True baseline rejects predicted late arrival and closes
            pending missed work. False permits late candidates and later responses;
            all arrivals still receive independent met/missed results.
        decision_times: Optional explicit nonnegative wake-ups for scripted tests;
            normal releases/arrivals/completions/deadlines already trigger decisions.
        route_planner: Optional independent routing callable; None preserves UCS.
            Strict mode caps selected travel at the remaining arrival budget.
            Returned durations are checked against graph costs; historical exposure
            is never used for arrivals, completion times or responder availability.

    Preconditions:
        Scenario validated, callback finite/prompt, no concurrent input mutation.
        No preemption/rerouting is supported. Float times are not fuzzily grouped;
        equality is exact and no tolerance admits early releases/late deadlines.

    Postconditions:
        Returns an immutable final result/log after all relevant queued work and
        explicit wake-ups. Source inputs/graph unchanged. Snapshot API never passes
        unreleased incidents to dispatchers. Deadline outcome is separate from work
        status. No actual road-failure model or guaranteed arrival is claimed.

    Raises:
        ValueError: Invalid policy/time/dispatch batch or unrepresentable time advance.
        Dispatcher exceptions propagate; an invalid run is not returned as success.
    """
    return _Simulator(scenario, graph, dispatcher, strict_deadlines, decision_times, route_planner).run()
