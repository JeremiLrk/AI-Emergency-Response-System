"""Online Boolean assignment optimization, following the course CSP formulation.

One x[r,i] per eligible candidate; at most one per responder and incident.
Objectives: lexicographic priority counts; optional on-time counts in late mode;
then minimum predicted response milliseconds. No deadline ranks, lookahead,
reservations, multi-job scheduling, routing choices or treatment-time objective.
"""
from dataclasses import dataclass
from math import ceil, fsum, isfinite
from time import monotonic

from .simulation_models import AssignmentRequest, DecisionSnapshot

PRIORITY_ORDER = ("Critical", "High", "Medium", "Low")


class AllocationError(RuntimeError):
    """An invalid model or unexpected infeasibility; never disguise this as no work.

    Parameters: standard RuntimeError message explaining the solver failure.
    Preconditions: raised for MODEL_INVALID/INFEASIBLE or an unexpected status.
    Postconditions: simulation aborts visibly instead of returning a successful run.
    """


@dataclass(frozen=True)
class SolvePhase:
    """One attempted objective level's solver diagnostics.

    Parameters:
        name: coverage/on_time priority level or response_milliseconds.
        status: CP-SAT status string or BUDGET_EXHAUSTED before a solve.
        objective_value: Exact integer achieved by the selected variables, or None.
        best_bound: Solver bound if a feasible solution exists, otherwise None.
        wall_seconds: Solver-reported wall time, zero when no solve was attempted.
    Preconditions: constructed by CspDispatcher; direct construction not validated.
    Postconditions: frozen audit record; FEASIBLE is not a proof of optimality.
    """
    name: str
    status: str
    objective_value: int | None
    best_bound: float | None
    wall_seconds: float


@dataclass(frozen=True)
class AllocationDiagnostic:
    """Outcome of one current-snapshot allocation call.

    Parameters:
        time: Current simulation seconds, not solver elapsed time.
        candidate_count: Number of eligible pair variables.
        phases: Attempted objective levels in order.
        status: Last solve status, NO_CANDIDATES or BUDGET_EXHAUSTED.
        lexicographic_optimal: True only when every relevant level was proven optimal.
        assigned_count: Number of requests returned.
        fallback_reason: None, valid earlier incumbent retained, or no incumbent.
    Preconditions: recorded after each normal allocator return or solver model error.
    Postconditions: no hidden future data; caller can distinguish timeout from no work.
    """
    time: float
    candidate_count: int
    phases: tuple[SolvePhase, ...]
    status: str
    lexicographic_optimal: bool
    assigned_count: int
    fallback_reason: str | None


def validate_snapshot(snapshot):
    """Validate allocator-facing facts without reading Scenario or external inputs.

    Parameters: snapshot is a DecisionSnapshot from the event controller.
    Preconditions: records have their documented types; original graph/incident
        stream are intentionally unavailable. Statistical road estimates are trusted.
    Postconditions: returns None if IDs, revealed timestamps and candidates are
        consistent. ValueError on duplicates, future exposure, ineligible pairs or
        inconsistent estimated times. Does not mutate input or regenerate routes.
    """
    if not isinstance(snapshot, DecisionSnapshot) or not isinstance(snapshot.strict_deadlines, bool):
        raise ValueError("Expected a simulation DecisionSnapshot with bool policy")
    if not isfinite(snapshot.time) or snapshot.time < 0:
        raise ValueError("Invalid current simulation time")
    responders = {r.id: r for r in snapshot.responders}
    incidents = {v.incident.id: v for v in snapshot.incidents}
    if len(responders) != len(snapshot.responders) or len(incidents) != len(snapshot.incidents):
        raise ValueError("Duplicate snapshot entity IDs")
    for view in snapshot.incidents:
        if view.incident.timestamp > snapshot.time:
            raise ValueError("Snapshot exposes an unreleased incident")
        if view.incident.priority not in PRIORITY_ORDER:
            raise ValueError("Unknown incident priority")
    seen = set()
    for candidate in snapshot.candidates:
        key = candidate.responder_id, candidate.incident_id
        if key in seen:
            raise ValueError("Duplicate assignment candidate")
        seen.add(key)
        if key[0] not in responders or key[1] not in incidents:
            raise ValueError("Candidate references unknown current entity")
        r, view = responders[key[0]], incidents[key[1]]
        i = view.incident
        if (r.status != "available" or r.available_at > snapshot.time
                or view.status != "pending" or i.required_capability not in r.capabilities):
            raise ValueError("Candidate violates availability/status/capability")
        route = candidate.route
        if (not route.nodes or route.nodes[0] != r.location or route.nodes[-1] != i.location
                or len(route.roads) != len(route.nodes)-1):
            raise ValueError("Candidate route endpoints/shape are inconsistent")
        times = (route.seconds, candidate.arrival_time, candidate.completion_time)
        if any(isinstance(v, bool) or not isinstance(v, (int, float))
               or not isfinite(v) or v < 0 for v in times):
            raise ValueError("Candidate contains invalid modeled times")
        if (candidate.arrival_time != fsum((snapshot.time, route.seconds))
                or candidate.completion_time != fsum((candidate.arrival_time, i.time_required))):
            raise ValueError("Candidate modeled times are inconsistent")
        on_time = candidate.arrival_time <= i.deadline
        if not isinstance(candidate.on_time, bool) or candidate.on_time != on_time:
            raise ValueError("Candidate on_time flag is inconsistent")
        if snapshot.strict_deadlines and not on_time:
            raise ValueError("Late candidate in a strict-deadline snapshot")


class CspDispatcher:
    """Select immediate assignments using OR-Tools CP-SAT, never future records.

    Parameters: see __init__ for budget/response precision settings.
    Preconditions: receives only current snapshots; each call builds a fresh model.
    Postconditions: returns compatible AssignmentRequest tuples and appends a
        diagnostic. No engine state, probability distribution or route is changed.
    """

    def __init__(self, *, time_limit_seconds=2.0, response_scale=1000):
        """Configure a shared wall-time budget per snapshot and integer precision.

        Parameters:
            self: New dispatcher instance.
            time_limit_seconds: Finite nonnegative budget across model building and
                all objective phases. Zero intentionally returns no incumbent.
            response_scale: Positive integer response-cost units per second;
                default 1000 uses ceil(response_seconds*1000). Execution stays float.
        Preconditions: settings checked; OR-Tools must be installed in this interpreter.
        Postconditions: empty diagnostics, fixed single-worker/seed solver settings.
            No file access, Scenario reference or incident lookahead is introduced.
        """
        if (isinstance(time_limit_seconds, bool) or not isinstance(time_limit_seconds, (int, float))
                or not isfinite(time_limit_seconds) or time_limit_seconds < 0):
            raise ValueError("Solver time limit must be finite nonnegative seconds")
        if isinstance(response_scale, bool) or not isinstance(response_scale, int) or response_scale < 1:
            raise ValueError("response_scale must be a positive integer")
        try:
            from ortools.sat.python import cp_model
        except ImportError as error:
            raise AllocationError("OR-Tools missing: install requirements.txt in your active environment") from error
        self.cp = cp_model
        self.time_limit_seconds = float(time_limit_seconds)
        self.response_scale = response_scale
        self.diagnostics = []

    def _solve_phase(self, model, remaining):
        """Solve one objective with the remaining shared budget.

        Parameters: self is dispatcher; model is current CpModel; remaining is
            strictly positive wall seconds. Called only with a validated model.
        Preconditions: remaining > 0; prior objective bounds are already fixed.
        Postconditions: returns (solver,status). No values may be read by the caller
            unless status is OPTIMAL or FEASIBLE. Search uses one worker/seed 0.
        """
        solver = self.cp.CpSolver()
        solver.parameters.max_time_in_seconds = remaining
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 0
        return solver, solver.solve(model)

    def __call__(self, snapshot):
        """Build/solve the approved hierarchy and return current dispatch requests.

        Parameters: self is dispatcher; snapshot is current DecisionSnapshot only.
        Preconditions: validate_snapshot checks candidates/revealed state. Callback
            callers must not concurrently mutate inputs; candidate routes are fixed.
        Postconditions: compatible requests; proven levels fixed only on OPTIMAL.
            FEASIBLE stops at that level without claiming hierarchy optimality;
            UNKNOWN/budget exhaustion retains a prior valid incumbent or returns ()
            with visible diagnostics. No deadline ranking or future planning occurs.
        Raises: ValueError for input/precision limits; AllocationError for invalid or
            unexpectedly infeasible model/status. Model errors are never no-work results.
        """
        started = monotonic()
        validate_snapshot(snapshot)
        candidates = tuple(sorted(snapshot.candidates, key=lambda c: (c.responder_id, c.incident_id)))
        if not candidates:
            self.diagnostics.append(AllocationDiagnostic(snapshot.time, 0, (), "NO_CANDIDATES", True, 0, None))
            return ()
        incidents = {v.incident.id: v.incident for v in snapshot.incidents if v.status == "pending"}
        model = self.cp.CpModel()
        x = [model.new_bool_var(f"x[{c.responder_id},{c.incident_id}]") for c in candidates]
        # Same Boolean sum constraints as course N-Queens rows/columns, but <=1:
        # emergencies/responders may remain unmatched when no feasible pairing exists.
        for responder in snapshot.responders:
            model.add(sum(x[k] for k, c in enumerate(candidates) if c.responder_id == responder.id) <= 1)
        y = {}
        for incident_id in sorted(incidents):
            y[incident_id] = model.new_bool_var(f"assigned[{incident_id}]")
            model.add(y[incident_id] == sum(x[k] for k, c in enumerate(candidates) if c.incident_id == incident_id))
        # Equality to a Boolean y already enforces at most one responder per incident.
        phases = []
        for priority in PRIORITY_ORDER:
            indices = [k for k, c in enumerate(candidates) if incidents[c.incident_id].priority == priority]
            if indices:
                # Store coefficients over x too, for exact incumbent-value accounting.
                phases.append((f"coverage_{priority}", True,
                    sum(y[i] for i in incidents if incidents[i].priority == priority),
                    tuple(1 if k in indices else 0 for k in range(len(x)))))
        if not snapshot.strict_deadlines:
            for priority in PRIORITY_ORDER:
                coefficients = tuple(int(c.on_time and incidents[c.incident_id].priority == priority) for c in candidates)
                if any(coefficients):
                    phases.append((f"on_time_{priority}", True,
                        sum(coefficient*variable for coefficient, variable in zip(coefficients, x)), coefficients))
        costs = []
        for c in candidates:
            try:
                scaled = (c.arrival_time-incidents[c.incident_id].timestamp)*self.response_scale
            except OverflowError as error:
                raise ValueError("Response objective exceeds supported integer precision") from error
            if not isfinite(scaled) or scaled < 0 or scaled > 2**62-1:
                raise ValueError("Response objective exceeds supported integer precision")
            costs.append(ceil(scaled))
        if sum(costs) > 2**62-1:
            raise ValueError("Response objective sum exceeds safe integer range")
        phases.append(("response_milliseconds" if self.response_scale == 1000 else "response_scaled",
                       False, sum(cost*variable for cost, variable in zip(costs, x)), tuple(costs)))
        validation_error = model.validate()
        if validation_error:
            self.diagnostics.append(AllocationDiagnostic(snapshot.time, len(x), (), "MODEL_INVALID", False, 0, validation_error))
            raise AllocationError(f"Invalid CP-SAT model: {validation_error}")
        incumbent = None
        phase_results = []
        status_name = "BUDGET_EXHAUSTED"
        complete = True
        reason = None
        for name, maximize, expression, coefficients in phases:
            remaining = self.time_limit_seconds-(monotonic()-started)
            if remaining <= 0:
                complete = False
                status_name = "BUDGET_EXHAUSTED"
                phase_results.append(SolvePhase(name, status_name, None, None, 0))
                reason = "previous_incumbent_retained" if incumbent is not None else "no_incumbent_available"
                break
            if maximize:
                model.maximize(expression)
            else:
                model.minimize(expression)
            solver, status = self._solve_phase(model, remaining)
            status_name = solver.status_name(status)
            if status in (self.cp.OPTIMAL, self.cp.FEASIBLE):
                incumbent = tuple(k for k, variable in enumerate(x) if solver.value(variable))
                value = sum(coefficients[k] for k in incumbent)
                phase_results.append(SolvePhase(name, status_name, value,
                                                float(solver.best_objective_bound), float(solver.wall_time)))
                if status == self.cp.FEASIBLE:
                    complete = False
                    reason = "feasible_solution_not_proven_optimal"
                    break  # Never freeze an unproven priority optimum.
                model.add(expression == value)
            elif status == self.cp.UNKNOWN:
                complete = False
                phase_results.append(SolvePhase(name, status_name, None, None, float(solver.wall_time)))
                reason = "previous_incumbent_retained" if incumbent is not None else "no_incumbent_available"
                break  # No solver.value calls are valid here.
            else:
                phase_results.append(SolvePhase(name, status_name, None, None, float(solver.wall_time)))
                self.diagnostics.append(AllocationDiagnostic(snapshot.time, len(x), tuple(phase_results),
                    status_name, False, 0, "solver_model_error"))
                raise AllocationError(f"Unexpected CP-SAT status {status_name}: optional assignments must admit all-zero")
        selected = () if incumbent is None else tuple(AssignmentRequest(candidates[k].responder_id,
                                                       candidates[k].incident_id) for k in incumbent)
        self.diagnostics.append(AllocationDiagnostic(snapshot.time, len(x), tuple(phase_results),
            status_name, complete, len(selected), reason))
        return selected
