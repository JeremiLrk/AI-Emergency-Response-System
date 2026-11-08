"""Exact Forward filtering of per-directed-road historical traffic observations.

Course HMM slides 3-7 define the model, slides 9 and 16-23 filtering/Forward.
We interpret initial as P(X1), update using observation 1 without a transition,
then alternate prediction and emission updates. Histories are available before
simulation time zero; no physical sampling interval or live updates are invented.
"""
from dataclasses import dataclass
from math import fsum

from .loaders import validate_traffic_probabilities
from .models import Scenario

STATES = ("Low", "Medium", "High")


@dataclass(frozen=True)
class TrafficBelief:
    """Full endpoint traffic belief with explicit evidence provenance.

    Parameters:
        probabilities: Fresh dict Low/Medium/High -> posterior probabilities.
        observation_count: Number of historical observations used; zero means prior.
    Preconditions: constructed by infer_traffic; direct construction not validated.
    Postconditions: frozen record, nested dict read-only by convention. It refers
        to the last historical state, used as a static simulation-start proxy;
        it is not a measured present/future traffic state or travel-time multiplier.
    """
    probabilities: dict[str, float]
    observation_count: int

    @property
    def prior_only(self):
        """Report lack of history without replacing uncertainty by Low.

        Parameters: self is a TrafficBelief.
        Preconditions: observation_count valid nonnegative integer.
        Postconditions: returns observation_count == 0, with no mutation.
        """
        return self.observation_count == 0


def forward_filter(probabilities, observations):
    """Compute P(X_n | e_1,...,e_n), or supplied initial prior for empty history.

    Parameters:
        probabilities: Scenario-specific initial/transition/emission dictionaries;
            transition[current][next], emission[hidden][observed].
        observations: Ordered iterable of Low/Medium/High observation labels.
    Preconditions: CPTs and labels checked. Initial is interpreted as P(X1), not
        P(X0). One transition connects consecutive ordinal historical steps;
        no assumption about seconds per step. Inputs must not change concurrently.
    Postconditions: fresh full probability dict, normalized after each observation.
        Formula: b1(x) proportional to initial(x)*emission(x,e1); for k>1,
        prediction(x)=sum_y b_prev(y)*T[y][x], then b(x) proportional to
        prediction(x)*emission[x][ek]. Inputs unchanged; no fitting, Viterbi,
        road-status inference, simulation events or routing choices occur.
    Raises: ValueError for invalid CPTs/labels or zero evidence likelihood,
        including numerical underflow; no fabricated fallback is supplied.
    """
    validate_traffic_probabilities(probabilities)
    belief = dict(probabilities["initial"])
    for index, observed in enumerate(observations):
        if observed not in STATES:
            raise ValueError(f"Invalid traffic observation: {observed!r}")
        # Emission first at step 1; inserting an initial transition changes the model.
        predicted = belief if index == 0 else {
            state: fsum(belief[previous] * probabilities["transition"][previous][state]
                        for previous in STATES) for state in STATES}
        weights = {state: predicted[state] * probabilities["emission"][state][observed]
                   for state in STATES}
        normalizer = fsum(weights.values())
        if normalizer <= 0:
            raise ValueError("Traffic evidence has zero likelihood or numerical underflow")
        belief = {state: weights[state]/normalizer for state in STATES}
    return belief


def infer_traffic(scenario: Scenario):
    """Filter each directed road's history exactly once at scenario startup.

    Parameters: scenario is validated input with its own HMM tables and histories.
    Preconditions: road keys unique; unknown histories, wrong road references,
        duplicate/gapped/nonpositive indices are checked again for direct callers.
        Only historical observation labels are used; no road reports are reused.
    Postconditions: returns (from,to) -> TrafficBelief for every road. Missing/empty
        histories use that scenario's prior. Existing histories are sorted by ordinal
        number without mutation; opposite directions never share evidence. No
        transitions are scheduled during simulation or across an unknown time gap.
    Raises: ValueError on structural/inference errors; source files are not read here.
    """
    validate_traffic_probabilities(scenario.traffic_probabilities)
    keys = {road.key for road in scenario.roads}
    if len(keys) != len(scenario.roads):
        raise ValueError("Duplicate directed road keys")
    if set(scenario.traffic_history)-keys:
        raise ValueError("Traffic history references an unknown directed road")
    result = {}
    for road in scenario.roads:
        rows = tuple(scenario.traffic_history.get(road.key, ()))
        if any(row.road != road.key for row in rows):
            raise ValueError("Traffic history stored under wrong directed road")
        if any(isinstance(row.observation_nr, bool) or not isinstance(row.observation_nr, int)
               for row in rows):
            raise ValueError("Traffic indices must be integer ordinals")
        rows = tuple(sorted(rows, key=lambda row: row.observation_nr))
        if [row.observation_nr for row in rows] != list(range(1, len(rows)+1)):
            raise ValueError("Traffic history needs unique contiguous indices starting at 1")
        result[road.key] = TrafficBelief(forward_filter(scenario.traffic_probabilities,
            (row.traffic_observation for row in rows)), len(rows))
    return result
