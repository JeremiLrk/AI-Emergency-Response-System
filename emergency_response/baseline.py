"""A simple comparison policy, not a CP-SAT substitute or risk guarantee."""
from .allocation import validate_snapshot
from .simulation_models import AssignmentRequest


class NearestDispatcher:
    """Greedily accept shortest-travel feasible pairs, ignoring priority.

    Parameters: no constructor arguments; each call takes a current snapshot.
    Preconditions: same candidate eligibility/routing/deadline policy as CP-SAT.
    Postconditions: one-pass compatible immediate requests. Sorting is deterministic
        by travel seconds/responder ID/incident ID. Not maximum matching or globally
        optimal; may waste specialists, miss emergencies or choose late work in late
        mode. These weaknesses make it a useful explicitly simple baseline.
    """

    def __call__(self, snapshot):
        """Select nearest compatible pairs without consulting any future input.

        Parameters: self is stateless baseline; snapshot is DecisionSnapshot.
        Preconditions: validate_snapshot enforces current-state eligibility.
        Postconditions: returns immutable AssignmentRequest tuple; input unchanged.
            No solver calls, deadlines ranks, reservations or priority bonuses.
        """
        validate_snapshot(snapshot)
        used_responders, used_incidents, selected = set(), set(), []
        for candidate in sorted(snapshot.candidates,
                key=lambda c: (c.route.seconds, c.responder_id, c.incident_id)):
            if candidate.responder_id in used_responders or candidate.incident_id in used_incidents:
                continue
            used_responders.add(candidate.responder_id)
            used_incidents.add(candidate.incident_id)
            selected.append(AssignmentRequest(candidate.responder_id, candidate.incident_id))
        return tuple(selected)
