"""Read-only evidence from actual decisions, never a second planning attempt.

Unknown route/arrival values mean 'not checked', especially for busy or unskilled
responders. These records describe this execution, not all possible allocations.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class EligibilityCheck:
    """One existing eligibility check for a revealed pending incident.

    Parameters: incident_id/responder_id identify the pair; capabilities are the
        responder's skills; required_capability is the incident's required skill;
        status/location/available_at copy the responder's current view.
        capable and available record the first two checks. reason is the first
        failing check, or eligible. route_exists, arrival_time and on_time are
        None when no route search was performed. eligible includes deadline policy.
    Preconditions: constructed from the simulator's checks, without extra search.
    Postconditions: frozen evidence; arrival_time is an estimate, never a promise.
    """
    incident_id: str
    responder_id: str
    capabilities: tuple[str, ...]
    required_capability: str
    status: str
    location: str | None
    available_at: float
    capable: bool
    available: bool
    reason: str
    route_exists: bool | None = None
    arrival_time: float | None = None
    on_time: bool | None = None
    eligible: bool = False


@dataclass(frozen=True)
class DecisionEvidence:
    """One actual decision while an incident was pending.

    Parameters: index distinguishes repeated decisions at the same time; time and
        deadline are absolute seconds; checks contains every current responder.
        selected_assignments copies the committed batch as (responder, incident)
        pairs. allocator_status/optimal copy existing CP-SAT diagnostics if present;
        None means the dispatcher supplied no such evidence.
    Preconditions: the batch has passed the simulator's normal validation.
    Postconditions: no future incidents or hypothetical assignments are recorded.
    """
    index: int
    time: float
    deadline: float
    checks: tuple[EligibilityCheck, ...]
    selected_assignments: tuple[tuple[str, str], ...]
    allocator_status: str | None = None
    optimal: bool | None = None


@dataclass(frozen=True)
class UnhandledExplanation:
    """Summary and complete observed history of one unhandled incident.

    Parameters: incident_id identifies the call; closure_reason is the simulator's
        existing final reason. ever_eligible_on_time concerns checked candidates
        only. earliest_checked_arrival/responder/decision_time identify the minimum
        arrival actually calculated, including late arrivals; None means none was
        calculated. decisions retains every pending decision, including repeats.
    Preconditions: build after execution; no inference about alternate allocations.
    Postconditions: diagnostic data only; no existing statistics are redefined.
    """
    incident_id: str
    closure_reason: str | None
    ever_eligible_on_time: bool
    earliest_checked_arrival: float | None
    earliest_responder_id: str | None
    earliest_decision_time: float | None
    decisions: tuple[DecisionEvidence, ...]


def record_check(checks, responder, incident, reason, **route_facts):
    """Copy an already-computed check into an optional collector.

    Parameters: checks is a list or None (recording disabled); responder/incident
        are current immutable views; reason names the result; route_facts supplies
        only values already calculated by eligibility logic.
    Preconditions: callers never search or estimate a busy responder's route here.
    Postconditions: appends one frozen record, or does nothing; returns None.
    """
    if checks is not None:
        checks.append(EligibilityCheck(
            incident.id, responder.id, tuple(sorted(responder.capabilities)), incident.required_capability,
            responder.status, responder.location, responder.available_at,
            incident.required_capability in responder.capabilities,
            responder.status == "available", reason, **route_facts))


def explain_unhandled(incidents, histories):
    """Summarize actual histories after the simulator closes pending work.

    Parameters: incidents are final IncidentViews; histories maps IDs to recorded
        DecisionEvidence lists. Preconditions: execution is finished.
    Postconditions: returns immutable explanations for closed unassigned work;
        performs no search, solver calls or changes to input records.
    """
    explanations = []
    for view in incidents:
        if view.status != "closed_unassigned":
            continue
        decisions = tuple(histories.get(view.incident.id, ()))
        arrivals = [(c.arrival_time, d.time, c.responder_id)
                    for d in decisions for c in d.checks if c.arrival_time is not None]
        earliest = min(arrivals) if arrivals else (None, None, None)
        explanations.append(UnhandledExplanation(
            view.incident.id, view.unassigned_reason,
            any(c.eligible and c.on_time for d in decisions for c in d.checks),
            earliest[0], earliest[2], earliest[1], decisions))
    return tuple(explanations)


def render_explanations(explanations):
    """Write a short, plain-language summary for each unhandled call.

    Parameters: explanations contains completed UnhandledExplanation records.
    Preconditions: histories contain only checks made during the actual run.
    Postconditions: returns report lines without changing records or statistics.
        The full timeline remains in the result, rather than repeating it here.
    """
    lines = ["", "--------------------------------------------------------",
             "Why incidents were not handled", "--------------------------------------------------------",
             "Times are seconds from the start. Arrival times are estimates.",
             "These reasons describe this run. Different earlier assignments could change the result."]
    for e in explanations:
        lines.extend(["", "--------------------------------------------------------", f"Incident {e.incident_id}"])
        checks = [c for d in e.decisions for c in d.checks]
        if e.ever_eligible_on_time:
            lines.append("  Reason: A responder could have arrived on time, but was not sent.")
        elif e.earliest_checked_arrival is not None and e.decisions and e.earliest_checked_arrival > e.decisions[0].deadline:
            lines.append("  Reason: Every arrival time checked was after the deadline.")
        elif not e.decisions:
            lines.append("  Reason: The incident closed before any assignment check was made.")
        elif not checks:
            lines.append("  Reason: There were no responders.")
        elif not any(c.capable for c in checks):
            lines.append("  Reason: No responder had the required skill.")
        else:
            lines.append("  Reason: No free responder with the right skill had a usable route.")

        if e.decisions:
            lines.append(f"  Arrival deadline: {e.decisions[0].deadline:.1f} seconds.")
        if e.earliest_checked_arrival is not None:
            lines.append(f"  Best arrival checked: {e.earliest_checked_arrival:.1f} seconds, by {e.earliest_responder_id}.")
            if e.decisions and e.earliest_checked_arrival > e.decisions[0].deadline:
                lines.append(f"  Too late by: {e.earliest_checked_arrival - e.decisions[0].deadline:.1f} seconds.")
        else:
            lines.append("  Best arrival checked: None. No arrival time was calculated.")

        # Include one concrete competition example, without guessing why it won.
        competition = next(((d, r, i) for d in e.decisions
                            for r, i in d.selected_assignments
                            if any(c.responder_id == r and c.eligible for c in d.checks)), None)
        if competition is not None:
            d, r, i = competition
            lines.append(f"  At {d.time:.1f} seconds, {r} was assigned to {i} instead.")
        if any(d.allocator_status in {"BUDGET_EXHAUSTED", "UNKNOWN"} and
               any(c.eligible for c in d.checks) for d in e.decisions):
            lines.append("  The solver ran out of time during at least one check with a possible assignment.")
        if any(c.capable and not c.available for c in checks):
            lines.append("  During some checks, responders with the right skill were busy.")
        if any(c.reason == "no_route" for c in checks):
            lines.append("  During some checks, no route was allowed by the road rules.")
        if e.closure_reason == "strict_deadline_unassigned":
            lines.append("  Outcome: Not sent; the strict deadline rule closed this incident.")
        else:
            lines.append("  Outcome: Not sent before the simulation ended.")
    lines.extend(["", "Full check-by-check details are available in the simulation result and command-line JSON."])
    return lines
