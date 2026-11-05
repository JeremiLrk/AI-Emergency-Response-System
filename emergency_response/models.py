"""Typed input records. Distances are metres; all times are seconds."""
from dataclasses import dataclass
from pathlib import Path

# Keep accessibility and traffic vocabularies separate, even where both imply delays.
ROAD_STATUSES = frozenset({"Open", "Congested", "Blocked"})
TRAFFIC_LEVELS = frozenset({"Low", "Medium", "High"})
WEATHER = frozenset({"Clear", "Rain", "Storm"})
# Join a report CSV source name to its source-specific likelihood table.
SOURCES = {"Citizen": "citizen_report", "Police": "police_report", "Sensor": "sensor_report"}
PRIORITIES = frozenset({"Critical", "High", "Medium", "Low"})
# Allowed capabilities by type; individual CSV rows can list only a subset.
CAPABILITIES = {
    "Ambulance": frozenset({"Medical emergency", "First aid", "CPR", "Life support"}),
    "PoliceUnit": frozenset({"Traffic control", "Security", "Evacuation", "Law enforcement"}),
    "FireTruck": frozenset({"Fire suppression", "Rescue", "Evacuation", "Pumping operations"}),
}


@dataclass(frozen=True)
class Node:
    """One named city location; x and y are coordinates in metres.

    The type (for example hospital) is descriptive input, not a routing restriction.

    Parameters:
        id: Nonempty string node identifier, unique within a scenario.
        name: Nonempty human-readable location name.
        x: Finite horizontal coordinate in metres.
        y: Finite vertical coordinate in metres.
        type: Nonempty descriptive location category, such as hospital.

    Preconditions:
        Callers constructing records directly must supply valid field values.
        load_scenario checks the described fields and scenario ID uniqueness; the
        dataclass itself does not.

    Postconditions:
        Creates a frozen input record storing these values, without adding a graph node
        or enforcing a routing restriction.
    """
    id: str
    name: str
    x: float
    y: float
    type: str


@dataclass(frozen=True)
class Road:
    """One directed road, with distance in metres and speed in metres/second.

    This record contains normal conditions only. Reports and estimated statuses are
    stored separately so uncertain evidence cannot silently become ground truth.

    Parameters:
        source: Departure node ID (CSV/JSON 'from').
        target: Arrival node ID (CSV/JSON 'to'); reverse direction is a separate road.
        distance: Finite nonnegative road length in metres.
        speed: Positive finite normal speed in metres/second, yielding a finite
            distance/speed.
        road_type: Nonempty descriptive category, such as main or secondary.

    Preconditions:
        Direct callers must supply valid fields and existing endpoints. load_scenario
        checks them and uniqueness of directed endpoint pairs; the dataclass does not.

    Postconditions:
        Creates a frozen normal-condition road record. No reverse road, inferred status
        or graph edge is created automatically.
    """
    source: str
    target: str
    distance: float
    speed: float
    road_type: str

    @property
    def key(self):
        """Return the directed endpoint pair used to join roads with evidence.

        Parameters:
            self: The Road instance receiving the call; passed automatically by Python.

        Preconditions:
            The record's endpoint fields describe the intended directed road; no validation
            occurs here.

        Postconditions:
            Returns (source, target) in that order, without modifying the record.
        """
        return self.source, self.target

    @property
    def id(self):
        # The data has no road ID. Directed endpoints uniquely identify a road.
        """Return a readable derived ID; the supplied JSON has no road-ID field.

        Parameters:
            self: The Road instance receiving the call; passed automatically by Python.

        Preconditions:
            source and target should be strings. For an unambiguous derived ID, endpoint
            strings must not themselves contain '->'; the loader does not check this
            convention.

        Postconditions:
            Returns the string 'source->target'. The record is unchanged; no global
            uniqueness check occurs.
        """
        return f"{self.source}->{self.target}"

    @property
    def normal_seconds(self):
        """Return normal travel time: metres / (metres/second) = seconds.

        Parameters:
            self: The Road instance receiving the call; passed automatically by Python.

        Preconditions:
            distance and speed must be numeric, with finite nonnegative distance, positive
            finite speed, and a finite quotient. load_scenario checks these conditions;
            direct Road construction does not.

        Postconditions:
            Returns distance/speed in seconds without rounding or changing the record. No
            congestion, traffic, waiting or service time is included.
        """
        return self.distance / self.speed


@dataclass(frozen=True)
class Responder:
    """A responder's initial input state, not a live simulation object.

    Capabilities are the explicitly listed subset, not every capability of its type.
    The loader checks that Available implies zero time_until_available. Busy time is
    a duration measured from simulation time zero. Future positions and jobs belong
    in separate simulation state rather than overwriting these input records.

    Parameters:
        id: Unique responder identifier in this scenario.
        type: Ambulance, PoliceUnit or FireTruck.
        start_location: Existing node where initial routing starts once ready.
        capabilities: Nonempty frozenset of explicitly listed capabilities permitted
            for this type.
        availability: Initial Available or Busy status.
        time_until_available: Finite nonnegative remaining duration from time zero, in
            seconds; must be zero when Available.

    Preconditions:
        Direct construction does not validate fields. load_scenario checks IDs, node
        references, allowed capabilities/type and availability consistency.

    Postconditions:
        Creates a frozen initial-state record; no live responder, scheduled job or
        future availability tracker is created.
    """
    id: str
    type: str
    start_location: str
    capabilities: frozenset[str]
    availability: str
    time_until_available: float

    @property
    def initial_ready_at(self):
        """Return the initial absolute release time in seconds.

        Because simulation starts at zero, the remaining busy duration equals this
        release time. This property does not track availability after later assignments.

        Parameters:
            self: The Responder instance receiving the call; passed automatically by
                Python.

        Preconditions:
            The record should contain nonnegative remaining seconds and use simulation time
            zero as its origin. The loader checks remaining time and Available/zero
            consistency; the property does not.

        Postconditions:
            Returns time_until_available unchanged as an initial absolute ready time. It
            does not update or calculate later availability.
        """
        return self.time_until_available


@dataclass(frozen=True)
class Incident:
    """An incident with an absolute release time and arrival deadline, in seconds.

    timestamp is when it becomes known; deadline is the latest arrival, inclusive.
    time_required is service duration after arrival, not an arrival-time constraint.
    These fields describe the input; this record does not schedule a responder.

    Parameters:
        id: Unique incident identifier in this scenario.
        location: Existing destination node ID.
        priority: Critical, High, Medium or Low.
        deadline: Finite nonnegative absolute latest arrival time, in seconds; equality
            is allowed in the design.
        required_capability: Single capability required from an assigned responder.
        timestamp: Finite nonnegative absolute release/knowledge time in seconds.
        time_required: Finite nonnegative service duration in seconds after arrival.

    Preconditions:
        Direct construction does not validate fields. load_scenario checks references,
        enums and numeric ranges; deadline >= timestamp and presence of a qualified
        responder are warnings, not guaranteed invariants.

    Postconditions:
        Creates a frozen incident record. Does not expose it before release or
        establish that any assignment can meet its deadline.
    """
    id: str
    location: str
    priority: str
    deadline: float
    required_capability: str
    timestamp: float
    time_required: float


@dataclass(frozen=True)
class RoadReport:
    """One noisy source report available at time zero for a directed road.

    source is Citizen, Police or Sensor, not the source node. Weather is known
    locally for this road; reported_status is evidence, not the true road condition.

    Parameters:
        source_node: Departure node of the reported directed road.
        target_node: Arrival node of the reported directed road.
        weather: Known local Clear/Rain/Storm weather for this road.
        source: Report origin Citizen/Police/Sensor, not a node ID.
        reported_status: Noisy Open/Congested/Blocked observation, not guaranteed
            truth.

    Preconditions:
        Direct construction does not validate fields. load_scenario checks the road,
        enums, per-road weather agreement and absence of duplicate source reports.

    Postconditions:
        Creates a frozen time-zero evidence record without inferring the actual road
        status.
    """
    source_node: str
    target_node: str
    weather: str
    source: str
    reported_status: str

    @property
    def road(self):
        """Return the directed road key matching Road.key.

        Parameters:
            self: The RoadReport instance receiving the call; passed automatically by
                Python.

        Preconditions:
            Endpoint fields refer to a directed input road; this is checked by
            load_scenario, not by this property.

        Postconditions:
            Returns (source_node, target_node) without changing the report.
        """
        return self.source_node, self.target_node


@dataclass(frozen=True)
class TrafficObservation:
    """One historical noisy traffic observation, available before time zero.

    observation_nr orders records within this directed road's history; it is not a
    simulation timestamp. source and target are node IDs. Both hidden traffic and
    observation labels use Low/Medium/High, but observations are not hidden truth.

    Parameters:
        observation_nr: Positive ordinal index within one directed road's historical
            sequence; not simulation seconds.
        source: Departure node ID for the observed road.
        target: Arrival node ID for the observed road.
        traffic_observation: Noisy Low/Medium/High traffic label.

    Preconditions:
        Direct construction does not validate fields. load_scenario checks
        road/label/index validity and contiguous unique sequences per road.

    Postconditions:
        Creates a frozen pre-simulation observation. It neither advances simulation
        time nor identifies the hidden traffic state.
    """
    observation_nr: int
    source: str
    target: str
    traffic_observation: str

    @property
    def road(self):
        """Return the directed road key used to group independent histories.

        Parameters:
            self: The TrafficObservation instance receiving the call; passed automatically
                by Python.

        Preconditions:
            Endpoint fields refer to a directed input road; this is checked by
            load_scenario, not by this property.

        Postconditions:
            Returns (source, target) without changing the observation.
        """
        return self.source, self.target


@dataclass(frozen=True)
class Scenario:
    """Validated inputs for one scenario, including future incident records.

    traffic_history maps directed endpoint pairs to observations sorted by index.
    Probability dictionaries are validated tables, not inferred beliefs. warnings
    describe missing evidence or obvious infeasibility without aborting loading.

    Frozen dataclasses prevent field reassignment, but nested dictionaries remain
    mutable Python objects. Treat them as read-only input by convention.

    Parameters:
        directory: Absolute pathlib.Path of the source scenario directory when produced
            by the loader.
        nodes: Tuple of all Node records.
        roads: Tuple of all directed Road records.
        responders: Tuple of initial Responder records.
        incidents: Tuple of all Incident records, including future incidents; loader
            orders by (timestamp,id).
        road_reports: Tuple of time-zero RoadReport evidence.
        traffic_history: Dict (source,target) -> tuple of historical observations
            ordered by ordinal index.
        road_probabilities: Validated Bayesian parameter tables; not computed road
            posteriors.
        traffic_probabilities: Validated initial/transition/emission HMM tables; not
            filtered beliefs.
        warnings: Tuple of nonfatal audit messages, such as missing evidence or obvious
            infeasibility.

    Preconditions:
        Use load_scenario for validation. Direct dataclass construction assumes all
        cross-record references and field constraints are already checked. Do not
        mutate nested input dictionaries while other components use them.

    Postconditions:
        Creates a frozen aggregate; nested dictionaries are not deeply immutable. No
        simulation, inference or allocation is executed.
    """
    directory: Path
    nodes: tuple[Node, ...]
    roads: tuple[Road, ...]
    responders: tuple[Responder, ...]
    incidents: tuple[Incident, ...]
    road_reports: tuple[RoadReport, ...]
    traffic_history: dict[tuple[str, str], tuple[TrafficObservation, ...]]
    road_probabilities: dict
    traffic_probabilities: dict
    warnings: tuple[str, ...]

    def known_incidents(self, now):
        """Return incidents released at or before now, in simulation seconds.

        Loading the full file does not authorize looking ahead. A future controller must
        use this view when planning. This method does not filter completed or expired
        incidents; tracking those requires simulation state, which is not implemented.

        Parameters:
            self: The Scenario instance receiving the call; passed automatically by Python.
            now: Current absolute simulation time in seconds, normally a finite nonnegative
                number.

        Preconditions:
            Incident timestamps and now must support numeric comparison. Finite nonnegative
            now and read-only input use are caller assumptions, not checked here.

        Postconditions:
            Returns a tuple containing exactly the records with timestamp <= now,
            preserving their input tuple order. No state changes. Assigned, expired or
            completed incidents are not removed by this view.
        """
        return tuple(incident for incident in self.incidents if incident.timestamp <= now)
