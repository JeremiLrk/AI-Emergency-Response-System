"""Modeled execution metrics with explicit handling of unhandled incidents."""
from collections import Counter
from dataclasses import dataclass
from math import fsum

from .simulation_models import SimulationResult


@dataclass(frozen=True)
class Statistics:
    """Summary of a completed modeled run, with seconds as the time unit.

    Parameters:
        total_incidents: All revealed incidents; full runs reveal all source inputs.
        handled: Completed treatment count, including late responses.
        deadlines_met: Arrived on time count, separate from completed status.
        unhandled: Total minus completed treatments.
        responders_used: Distinct responders in dispatch commitments.
        average_response_seconds: Mean arrival-release over completed incidents;
            None when none completed, never a misleading zero in that case.
        deadlines_met_percent_all: Met/all incidents *100; None for an empty stream.
        deadlines_met_percent_handled: Met/completed *100; None if none handled.
        handled_by_priority: Completed counts, for interpreting priority tradeoffs.
    Preconditions: constructed by summarize on a final valid SimulationResult.
    Postconditions: frozen summary (nested priority dict treated read-only).
        Measures modeled execution, not actual road-failure/forecast accuracy.
    """
    total_incidents: int
    handled: int
    deadlines_met: int
    unhandled: int
    responders_used: int
    average_response_seconds: float | None
    deadlines_met_percent_all: float | None
    deadlines_met_percent_handled: float | None
    handled_by_priority: dict[str, int]


def summarize(result: SimulationResult):
    """Calculate coverage/deadlines/mean response without rewarding unhandled work.

    Parameters: result is a final execution returned by simulate, not a partial view.
    Preconditions: simulator invariants hold; completed records have arrival times.
    Postconditions: returns Statistics. Unhandled incidents count as not met in the
        all-incident denominator, and are excluded (reported separately) from the
        average response denominator. Input unchanged; no times are rounded.
    """
    completed = [v for v in result.incidents if v.status == "completed"]
    responses = [v.arrival_time-v.incident.timestamp for v in completed]
    met = sum(v.deadline_result == "met" for v in result.incidents)
    total, handled = len(result.incidents), len(completed)
    priorities = Counter(v.incident.priority for v in completed)
    return Statistics(total, handled, met, total-handled,
        len({a.responder_id for a in result.assignments}),
        fsum(responses)/handled if handled else None,
        100*met/total if total else None, 100*met/handled if handled else None,
        {p: priorities[p] for p in ("Critical", "High", "Medium", "Low")})
