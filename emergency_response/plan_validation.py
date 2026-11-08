"""Independent replay of assignment-section-5.1 plans against original inputs.

No simulator, search, graph builder, allocator or exported timing fields are used.
The supplied Bayesian inference is reused, but road filtering/costs and resource
timelines are reconstructed here. Validity is relative to explicit estimates and
deadline policy, never a proof of optimality, hidden road truth or future-blindness.
"""
from collections import Counter
from dataclasses import dataclass
import json
from math import fsum, isfinite
from pathlib import Path

from .bayesian import infer_scenario
from .statistics import Statistics


@dataclass(frozen=True)
class PlanIssue:
    """One validation finding.

    Parameters: row is original zero-based plan index (None for whole document);
        code is stable error category; message explains the violated constraint.
    Preconditions: created by validate_plan; fields do not validate themselves.
    Postconditions: immutable diagnostic; no claim about other rows being correct.
    """
    row: int | None
    code: str
    message: str


@dataclass(frozen=True)
class ReplayedAssignment:
    """Times independently reconstructed from a schema-valid plan row.

    Parameters: row identifies original entry; responder_id/incident_id are input
        references; departure_time is plan time; travel_seconds is original-road
        estimate; arrival_time and completion_time include travel and treatment;
        on_time tests arrival <= absolute incident deadline.
    Preconditions: original scenario validated; row has usable references/path.
    Postconditions: immutable estimate, possibly accompanied by validation errors
        in the report. A reconstructed row alone is not a validity certificate.
    """
    row: int
    responder_id: str
    incident_id: str
    departure_time: float
    travel_seconds: float
    arrival_time: float
    completion_time: float
    on_time: bool


@dataclass(frozen=True)
class PlanValidation:
    """Policy-relative validity, deadline compliance and independent replay metrics.

    Parameters: valid means no errors under selected policy; strict_deadlines is
        the selected arrival rule; deadline_compliant means every assigned arrival
        is on time AND the plan has no errors; errors/warnings explain failures or
        permitted lateness; assignments are chronological replay records;
        unhandled_incident_ids are absent from replay; statistics is independent
        final-run summary when valid, otherwise None to avoid scoring invalid work.
    Preconditions: created by validate_plan, with original validated Scenario.
    Postconditions: frozen report. An empty plan is valid but may perform poorly.
        Deadline compliance does not mean all incidents were handled. Late-mode
        validity is not strict assignment-deadline compliance. No optimality claim.
    """
    valid: bool
    strict_deadlines: bool
    deadline_compliant: bool
    errors: tuple[PlanIssue, ...]
    warnings: tuple[PlanIssue, ...]
    assignments: tuple[ReplayedAssignment, ...]
    unhandled_incident_ids: tuple[str, ...]
    statistics: Statistics | None


def _unique_object(pairs):
    """Reject duplicate JSON object keys rather than silently overwriting evidence.

    Parameters: pairs is decoder-provided sequence of (key,value).
    Preconditions: called as json object_pairs_hook.
    Postconditions: returns dict or raises ValueError on any duplicate key.
    """
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    """Reject JSON NaN/Infinity extensions; value names the decoded constant.

    Preconditions: called by JSON decoder. Postconditions: always raises ValueError.
    """
    raise ValueError(f"Nonstandard JSON numeric constant: {value}")


def load_plan(path):
    """Read strict JSON without interpreting assignments or trusting extra metadata.

    Parameters: path is readable UTF-8 plan.json (an optional BOM is accepted).
    Preconditions: file exists/readable; no concurrent file mutation.
    Postconditions: returns decoded document for validate_plan; rejects malformed
        JSON, duplicate keys and nonstandard NaN/Infinity. No scenario/file changes.
    """
    return json.loads(Path(path).read_text(encoding="utf-8-sig"),
                      object_pairs_hook=_unique_object, parse_constant=_invalid_constant)


def _advance(start, duration):
    """Independently add a nonnegative duration without losing positive intervals.

    Parameters: start/duration are finite nonnegative seconds.
    Preconditions: caller validated values and source durations.
    Postconditions: finite representable result or ValueError; no tolerance admits
        early release, overlapping service or late strict arrival.
    """
    try:
        end = fsum((start, duration))
    except OverflowError as error:
        raise ValueError("Unrepresentable event time") from error
    if not isfinite(end) or (duration > 0 and end <= start):
        raise ValueError("Unrepresentable event time")
    return end


def validate_plan(scenario, plan, *, routing_policy="baseline", blocked_threshold=None,
                  strict_deadlines=True):
    """Replay a plan from original roads/responders/incidents, independently of execution.

    Parameters:
        scenario: Original validated Scenario, not SimulationResult or graph.
        plan: Decoded JSON list of exactly responder_id,incident_id,path,time rows.
        routing_policy: baseline (all-open estimates) or bayesian (posterior-
            conditional seconds and configured blocked-edge threshold).
        blocked_threshold: Required finite fraction [0,1] for bayesian, otherwise
            None; must match the run. plan.json intentionally has no extra wrapper.
        strict_deadlines: True rejects every late arrival; False warns and records
            lateness without relaxing capabilities, releases, paths or occupancy.
    Preconditions: scenario passed load_scenario and remains unchanged. Configuration
        checked; bad plan content becomes diagnostics rather than an exception.
    Postconditions: PlanValidation with chronological reconstruction and independently
        computed Statistics only when valid. Unknown IDs, duplicate incidents, early
        dispatch, missing capability, unavailable units, invalid directed paths,
        rejected roads and invalid numbers/schema are errors. Responders may work
        again at exact completion, remaining at the incident; initially busy units
        become ready at their supplied start location. Unhandled incidents allowed.
        Does not require shortest routes, good priority decisions or optimal scores;
        cannot establish absence of future-aware reasoning from final output alone.
    Raises: ValueError for configuration or inconsistent original scenario input.
    """
    if not isinstance(strict_deadlines, bool) or routing_policy not in {"baseline", "bayesian"}:
        raise ValueError("Expected bool strict_deadlines and baseline/bayesian routing policy")
    if routing_policy == "baseline":
        if blocked_threshold is not None:
            raise ValueError("Baseline validation does not use a blockage threshold")
    elif (isinstance(blocked_threshold, bool) or not isinstance(blocked_threshold, (int,float))
          or not isfinite(blocked_threshold) or not 0 <= blocked_threshold <= 1):
        raise ValueError("Bayesian validation requires a finite blockage threshold in [0,1]")
    responders = {r.id:r for r in scenario.responders}
    incidents = {i.id:i for i in scenario.incidents}
    nodes = {n.id for n in scenario.nodes}
    roads = {r.key:r for r in scenario.roads}
    if (len(responders) != len(scenario.responders) or len(incidents) != len(scenario.incidents)
            or len(roads) != len(scenario.roads)):
        raise ValueError("Original input IDs/directed road keys must be unique")
    beliefs = infer_scenario(scenario) if routing_policy == "bayesian" else None
    errors, warnings, entries, replayed = [], [], [], []
    if not isinstance(plan, list):
        errors.append(PlanIssue(None,"schema","plan.json must be a top-level list"))
        plan = []
    seen_incidents = set()
    for index, row in enumerate(plan):
        if not isinstance(row, dict) or set(row) != {"responder_id","incident_id","path","time"}:
            errors.append(PlanIssue(index,"schema","Expected exactly responder_id, incident_id, path, time"))
            continue
        if any(not isinstance(row[k],str) or not row[k] for k in ("responder_id","incident_id")):
            errors.append(PlanIssue(index,"schema","Responder/incident IDs must be nonempty strings"))
            continue
        if (not isinstance(row["path"],list) or not row["path"] or
                any(not isinstance(n,str) or n not in nodes for n in row["path"])):
            errors.append(PlanIssue(index,"path","Path must be a nonempty list of existing node IDs"))
            continue
        time = row["time"]
        try:
            valid_time = not isinstance(time,bool) and isinstance(time,(int,float)) and isfinite(time) and time >= 0
        except OverflowError:
            valid_time = False
        if not valid_time:
            errors.append(PlanIssue(index,"time","Start time must be finite nonnegative seconds, not bool"))
            continue
        if row["responder_id"] not in responders or row["incident_id"] not in incidents:
            errors.append(PlanIssue(index,"reference","Unknown responder or incident ID"))
            continue
        if row["incident_id"] in seen_incidents:
            errors.append(PlanIssue(index,"duplicate_incident","An incident may be assigned only once"))
        seen_incidents.add(row["incident_id"])
        entries.append((time,index,row))
    # Stable order supports zero-duration consecutive jobs at the same instant.
    # JSON list ordering is otherwise not required to be chronological.
    ready = {r.id:r.time_until_available for r in scenario.responders}
    locations = {r.id:r.start_location for r in scenario.responders}
    for time, index, row in sorted(entries, key=lambda item:(item[0],item[1])):
        responder, incident = responders[row["responder_id"]], incidents[row["incident_id"]]
        if incident.required_capability not in responder.capabilities:
            errors.append(PlanIssue(index,"capability","Responder lacks required incident capability"))
        if time < incident.timestamp:
            errors.append(PlanIssue(index,"release","Dispatch precedes incident release"))
        if time < ready[responder.id]:
            errors.append(PlanIssue(index,"availability","Responder still initially busy, travelling or treating"))
        if row["path"][0] != locations[responder.id] or row["path"][-1] != incident.location:
            errors.append(PlanIssue(index,"endpoint","Path must start at current responder location and end at incident"))
        travel, path_ok = 0.0, True
        for a, b in zip(row["path"],row["path"][1:]):
            road = roads.get((a,b))
            if road is None:
                errors.append(PlanIssue(index,"directed_road",f"No original directed road {a}->{b}"))
                path_ok = False
                break
            seconds = road.distance/road.speed
            if beliefs is not None:
                belief = beliefs[road.key]
                traversable = belief["Open"]+belief["Congested"]
                if belief["Blocked"] >= blocked_threshold or traversable <= 0:
                    errors.append(PlanIssue(index,"blocked_road",f"Road {a}->{b} excluded by declared Bayesian policy"))
                    path_ok = False
                    break
                seconds *= (belief["Open"]+1.5*belief["Congested"])/traversable
            # Match ordinary route accumulation, independently of Route/Graph.
            travel += seconds
        if not path_ok:
            continue
        try:
            if not isfinite(travel):
                raise ValueError("Nonfinite travel duration")
            arrival = _advance(time,travel)
            completion = _advance(arrival,incident.time_required)
        except ValueError as error:
            errors.append(PlanIssue(index,"duration",str(error)))
            continue
        on_time = arrival <= incident.deadline
        if not on_time:
            issue = PlanIssue(index,"deadline","Estimated arrival exceeds absolute arrival deadline")
            (errors if strict_deadlines else warnings).append(issue)
        replayed.append(ReplayedAssignment(index,responder.id,incident.id,time,travel,arrival,completion,on_time))
        ready[responder.id] = completion
        locations[responder.id] = incident.location
    assigned = {a.incident_id for a in replayed}
    unhandled = tuple(sorted(set(incidents)-assigned))
    valid = not errors
    statistics = None
    if valid:
        handled, total = len(replayed), len(incidents)
        met = sum(a.on_time for a in replayed)
        priority_counts = Counter(incidents[a.incident_id].priority for a in replayed)
        statistics = Statistics(total,handled,met,total-handled,
            len({a.responder_id for a in replayed}),
            fsum(a.arrival_time-incidents[a.incident_id].timestamp for a in replayed)/handled if handled else None,
            100*met/total if total else None,100*met/handled if handled else None,
            {p:priority_counts[p] for p in ("Critical","High","Medium","Low")})
    return PlanValidation(valid,strict_deadlines,valid and all(a.on_time for a in replayed),
                          tuple(errors),tuple(warnings),tuple(replayed),unhandled,statistics)
