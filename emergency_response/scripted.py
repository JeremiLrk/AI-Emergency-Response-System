"""Scripted dispatch fixtures, independent of the event controller and future CSP."""
from collections.abc import Mapping
from math import isfinite

from .loaders import read_json
from .simulation_models import AssignmentRequest, DecisionSnapshot


class ScriptedDispatcher:
    """Consume explicit immediate dispatch batches at scheduled decision times.

    Parameters: schedule maps numeric seconds to iterables of AssignmentRequest.
    Preconditions: times finite/nonnegative, IDs nonempty strings; checked here.
    Postconditions: copied schedule is consumed once per timestamp, including when
        zero-duration events cause several callback rounds at that time. This is
        a mechanical test fixture, not an online allocation algorithm. A script's
        author can know future input; the engine still rejects premature dispatch.
    """

    def __init__(self, schedule):
        """Copy/validate script batches without inspecting scenario incident files.

        Parameters: self is new dispatcher; schedule is time -> request iterable.
        Preconditions: mapping and typed requests required; times/IDs checked.
        Postconditions: decision_times lists explicit wake-ups; no source mutation.
        """
        if not isinstance(schedule, Mapping):
            raise ValueError("Script schedule must be a mapping")
        self._remaining = {}
        for time, batch in schedule.items():
            if (isinstance(time, bool) or not isinstance(time, (int, float))
                    or not isfinite(time) or time < 0):
                raise ValueError("Script times must be finite nonnegative seconds")
            requests = tuple(batch)
            for request in requests:
                if not isinstance(request, AssignmentRequest):
                    raise ValueError("Script entries must be AssignmentRequest objects")
                if any(not isinstance(value, str) or not value for value in
                       (request.responder_id, request.incident_id)):
                    raise ValueError("Script IDs must be nonempty strings")
            self._remaining[float(time)] = requests
        self.decision_times = tuple(sorted(self._remaining))

    def __call__(self, snapshot: DecisionSnapshot):
        """Return this time's batch once, or no assignments at other decision points.

        Parameters: self is dispatcher; snapshot is the current immutable view.
        Preconditions: a fresh dispatcher instance is used for each simulation.
        Postconditions: returns tuple of requests, consumes only current timestamp.
            Does not change snapshot; engine independently validates all proposals.
        """
        return self._remaining.pop(snapshot.time, ())


def load_script(path):
    """Read a JSON array of {time, responder_id, incident_id} script records.

    Parameters: path is a readable UTF-8 JSON filename/path.
    Preconditions: records have exactly those keys, numeric finite nonnegative
        times and nonempty string IDs; checked. Scenario eligibility is not known
        here and is checked at dispatch time by the simulator.
    Postconditions: returns a fresh ScriptedDispatcher, grouping same-time records
        into one batch. Source file unchanged. Invalid structure raises ValueError;
        file/JSON errors propagate. No optimization or future-state access occurs.
    """
    records = read_json(path)
    if not isinstance(records, list):
        raise ValueError("Script JSON must be an array")
    schedule = {}
    for row in records:
        if not isinstance(row, dict) or set(row) != {"time", "responder_id", "incident_id"}:
            raise ValueError("Script record needs time, responder_id and incident_id")
        time = row["time"]
        if (isinstance(time, bool) or not isinstance(time, (int, float))
                or not isfinite(time) or time < 0):
            raise ValueError("Invalid script time")
        schedule.setdefault(time, []).append(AssignmentRequest(row["responder_id"], row["incident_id"]))
    return ScriptedDispatcher(schedule)
