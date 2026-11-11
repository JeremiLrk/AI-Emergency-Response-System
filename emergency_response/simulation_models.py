"""Immutable dispatcher views and recorded modeled-execution results.

Times are absolute simulation seconds, except Route.seconds (travel duration).
Deadline results and work status are deliberately separate. These data classes
store values; the simulator checks transitions and constructs validated views.
"""
from dataclasses import dataclass

from .diagnostics import UnhandledExplanation
from .models import Incident
from .search import Route


@dataclass(frozen=True)
class AssignmentRequest:
    """An immediate dispatch proposal; no caller-supplied times or routes.

    Parameters:
        responder_id: Currently available responder to dispatch.
        incident_id: Currently revealed, pending incident to handle.
    Preconditions:
        IDs are strings. The simulator checks eligibility against its own state.
    Postconditions:
        Frozen proposal only; constructing one does not commit an assignment.
    """
    responder_id: str
    incident_id: str


@dataclass(frozen=True)
class ResponderView:
    """Read-only operational state supplied to a dispatcher or final result.

    Parameters:
        id: Responder identifier.
        capabilities: Explicit immutable capability set.
        status: initially_busy, available, travelling or treating.
        location: Current node when available/treating; None when travelling or
            initially busy with an unknown pre-existing job position.
        available_at: Initial readiness or current modeled job completion time;
            may be in the past for an idle responder.
        incident_id: Committed incident ID, or None for idle/initially busy state.
    Preconditions:
        Direct construction assumes consistent values; the simulator maintains them.
    Postconditions:
        Frozen snapshot with no mutable simulator state or future incident records.
    """
    id: str
    capabilities: frozenset[str]
    status: str
    location: str | None
    available_at: float
    incident_id: str | None


@dataclass(frozen=True)
class IncidentView:
    """A revealed incident's work state and independent deadline outcome.

    Parameters:
        incident: Frozen input record, only exposed after timestamp is reached.
        status: pending, travelling, treating, completed or closed_unassigned.
        deadline_result: not_due, met or missed; missed need not imply abandoned.
        responder_id: Assigned responder, or None if never assigned.
        arrival_time: Modeled arrival event time, None until arrival occurs.
        completion_time: Modeled completion event time, None until completed.
        unassigned_reason: Closure policy reason, or None while open/handled.
    Preconditions:
        Direct construction assumes consistency; the simulator creates these views.
    Postconditions:
        Frozen record. In allow-late mode completed+missed is a valid combination.
    """
    incident: Incident
    status: str
    deadline_result: str
    responder_id: str | None = None
    arrival_time: float | None = None
    completion_time: float | None = None
    unassigned_reason: str | None = None


@dataclass(frozen=True)
class Candidate:
    """A validated immediate responder/incident route candidate, not a commitment.

    Parameters:
        responder_id: Free, capable responder at the route's starting node.
        incident_id: Revealed pending incident at the destination.
        route: UCS route in the fixed private routing snapshot.
        arrival_time: Current time plus estimated route duration.
        completion_time: Arrival plus incident treatment duration.
        on_time: Whether modeled arrival <= absolute deadline.
    Preconditions:
        The simulator constructs values; direct construction does not validate them.
    Postconditions:
        Frozen candidate. Strict snapshots exclude late candidates; allow-late
        snapshots may contain on_time=False without changing other constraints.
    """
    responder_id: str
    incident_id: str
    route: Route
    arrival_time: float
    completion_time: float
    on_time: bool


@dataclass(frozen=True)
class DecisionSnapshot:
    """The entire supported allocator interface: current immutable state only.

    Parameters:
        time: Current absolute simulation seconds.
        responders: Operational views of all responders, including busy ones.
        incidents: Views of revealed incidents only, including past outcomes.
        candidates: Immediate eligible assignments under the selected deadline policy.
        strict_deadlines: Whether late-arrival candidates are excluded.
    Preconditions:
        Constructed after batching releases/state changes; no future incident input,
        Scenario reference, event queue or mutable engine object may be passed here.
    Postconditions:
        Frozen snapshot. This is an API information boundary, not a security sandbox
        against a malicious Python callback that obtains files through other means.
    """
    time: float
    responders: tuple[ResponderView, ...]
    incidents: tuple[IncidentView, ...]
    candidates: tuple[Candidate, ...]
    strict_deadlines: bool


@dataclass(frozen=True)
class AssignmentRecord:
    """A non-preemptive dispatch commitment retained for replay and inspection.

    Parameters:
        responder_id: Selected responder.
        incident_id: Selected revealed incident.
        departure_time: Assignment start, the eventual plan.json 'time' value.
        route: Frozen route selected at departure.
        arrival_time: Scheduled modeled arrival, not guaranteed real-world arrival.
        completion_time: Scheduled modeled treatment completion.
    Preconditions:
        The simulator creates this only after validating the whole dispatch batch.
    Postconditions:
        Frozen historical commitment; subsequent releases cannot reassign it.
    """
    responder_id: str
    incident_id: str
    departure_time: float
    route: Route
    arrival_time: float
    completion_time: float


@dataclass(frozen=True)
class SimulationEvent:
    """One processed state-transition log entry, in stable processing order.

    Parameters:
        time: Absolute modeled event time.
        kind: release, initial_available, dispatch, arrival, completion,
            deadline_missed or closed_unassigned.
        responder_id: Affected responder or None.
        incident_id: Affected incident or None.
        message: Human-readable detail, not data used for scheduling.
    Preconditions:
        The simulator supplies identifiers appropriate to the event kind.
    Postconditions:
        Frozen log entry; scheduled future events are not exposed to dispatchers.
    """
    time: float
    kind: str
    responder_id: str | None = None
    incident_id: str | None = None
    message: str = ""


@dataclass(frozen=True)
class SimulationResult:
    """Final modeled execution, not a claim of uncertain-road ground truth.

    Parameters:
        time: Last relevant processed event time in seconds.
        strict_deadlines: Selected deadline policy.
        assignments: Chronological dispatch commitments.
        responders: Final immutable operational states.
        incidents: Final states with deadline results tracked independently.
        events: Processed transition log, excluding irrelevant queued deadlines.
        unhandled_explanations: Optional diagnostic histories, excluded from planning
            and metrics. Empty for older manually constructed or recording-off results.
    Preconditions:
        Created after the event queue is drained and remaining pending work closed.
    Postconditions:
        No active travel/treatment remains. Initially busy responders have been
        released. Unhandled incidents are explicit, not counted as successful work.
    """
    time: float
    strict_deadlines: bool
    assignments: tuple[AssignmentRecord, ...]
    responders: tuple[ResponderView, ...]
    incidents: tuple[IncidentView, ...]
    events: tuple[SimulationEvent, ...]
    unhandled_explanations: tuple[UnhandledExplanation, ...] = ()
