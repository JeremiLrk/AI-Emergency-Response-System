"""Typed input records. Distances are metres; all times are seconds."""
from dataclasses import dataclass
from pathlib import Path

ROAD_STATUSES = frozenset({"Open", "Congested", "Blocked"})
TRAFFIC_LEVELS = frozenset({"Low", "Medium", "High"})
WEATHER = frozenset({"Clear", "Rain", "Storm"})
SOURCES = {"Citizen": "citizen_report", "Police": "police_report", "Sensor": "sensor_report"}
PRIORITIES = frozenset({"Critical", "High", "Medium", "Low"})
CAPABILITIES = {
    "Ambulance": frozenset({"Medical emergency", "First aid", "CPR", "Life support"}),
    "PoliceUnit": frozenset({"Traffic control", "Security", "Evacuation", "Law enforcement"}),
    "FireTruck": frozenset({"Fire suppression", "Rescue", "Evacuation", "Pumping operations"}),
}


@dataclass(frozen=True)
class Node:
    id: str
    name: str
    x: float
    y: float
    type: str


@dataclass(frozen=True)
class Road:
    source: str
    target: str
    distance: float
    speed: float
    road_type: str

    @property
    def key(self):
        return self.source, self.target

    @property
    def id(self):
        # The data has no road ID. Directed endpoints uniquely identify a road.
        return f"{self.source}->{self.target}"

    @property
    def normal_seconds(self):
        return self.distance / self.speed


@dataclass(frozen=True)
class Responder:
    id: str
    type: str
    start_location: str
    capabilities: frozenset[str]
    availability: str
    time_until_available: float

    @property
    def initial_ready_at(self):
        return self.time_until_available


@dataclass(frozen=True)
class Incident:
    id: str
    location: str
    priority: str
    deadline: float
    required_capability: str
    timestamp: float
    time_required: float


@dataclass(frozen=True)
class RoadReport:
    source_node: str
    target_node: str
    weather: str
    source: str
    reported_status: str

    @property
    def road(self):
        return self.source_node, self.target_node


@dataclass(frozen=True)
class TrafficObservation:
    observation_nr: int
    source: str
    target: str
    traffic_observation: str

    @property
    def road(self):
        return self.source, self.target


@dataclass(frozen=True)
class Scenario:
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
        """Parsing a future incident does not make it available for planning."""
        return tuple(incident for incident in self.incidents if incident.timestamp <= now)
