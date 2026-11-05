"""Load and validate the supplied Scenarios/ScenarioN input schema.

Errors carry a filename and record context. Probabilities are checked, never
silently normalized. Missing report/history coverage is allowed and reported.
"""
import csv
import json
from pathlib import Path
from math import isfinite, isclose

from .models import (Node, Road, Responder, Incident, RoadReport,
                     TrafficObservation, Scenario, ROAD_STATUSES, TRAFFIC_LEVELS,
                     WEATHER, SOURCES, PRIORITIES, CAPABILITIES)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f"Nonstandard JSON constant: {value}")


def read_json(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        return json.load(stream, object_pairs_hook=_unique_object,
                         parse_constant=_invalid_constant)


def read_csv(path, *, delimiter=",", columns=None):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=delimiter, strict=True)
        headers = reader.fieldnames
        if not headers or any(not h for h in headers) or len(set(headers)) != len(headers):
            raise ValueError(f"{path}: CSV needs nonempty, unique column names")
        if columns is not None and set(headers) != set(columns):
            raise ValueError(f"{path}: expected columns {sorted(columns)}, got {headers}")
        rows = []
        for line, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{path}: CSV row width differs from header at record {line}")
            rows.append(row)
        return rows


def _fields(value, expected, context):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f"{context}: expected fields {sorted(expected)}")


def _text(value, context):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{context}: expected nonempty text without surrounding whitespace")
    return value


def _number(value, context, *, minimum=None, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{context}: expected a finite number")
    try:
        result = float(value)
    except ValueError as error:
        raise ValueError(f"{context}: invalid number {value!r}") from error
    if not isfinite(result) or (minimum is not None and result < minimum) or (positive and result <= 0):
        raise ValueError(f"{context}: invalid numeric range {value!r}")
    return result


def _choice(value, choices, context):
    if value not in choices:
        raise ValueError(f"{context}: {value!r} must be one of {sorted(choices)}")
    return value


def _unique(value, seen, context):
    if value in seen:
        raise ValueError(f"{context}: duplicate {value!r}")
    seen.add(value)


def _distribution(value, labels, context):
    _fields(value, labels, context)
    for label, probability in value.items():
        if isinstance(probability, bool) or not isinstance(probability, (int, float)):
            raise ValueError(f"{context}.{label}: probability must be numeric")
        if not isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError(f"{context}.{label}: probability outside [0, 1]")
    if not isclose(sum(value.values()), 1.0, rel_tol=0, abs_tol=1e-9):
        raise ValueError(f"{context}: probabilities must sum to 1")


def _matrix(value, outer, inner, context):
    _fields(value, outer, context)
    for label in outer:
        _distribution(value[label], inner, f"{context}.{label}")


def validate_road_probabilities(data):
    _fields(data, {"weather_prior", "road_status_given_weather", *SOURCES.values()}, "road_probabilities.json")
    _distribution(data["weather_prior"], WEATHER, "weather_prior")
    _matrix(data["road_status_given_weather"], WEATHER, ROAD_STATUSES, "road_status_given_weather")
    for table in SOURCES.values():
        # Outer: true status. Inner: reported status. P(report | true status).
        _matrix(data[table], ROAD_STATUSES, ROAD_STATUSES, table)


def validate_traffic_probabilities(data):
    _fields(data, {"initial", "transition", "emission"}, "traffic_probabilities.json")
    _distribution(data["initial"], TRAFFIC_LEVELS, "initial")
    # transition[current][next]; emission[hidden][observed].
    for table in ("transition", "emission"):
        _matrix(data[table], TRAFFIC_LEVELS, TRAFFIC_LEVELS, table)


def load_scenario(directory) -> Scenario:
    root = Path(directory)
    data = read_json(root / "city_graph.json")
    _fields(data, {"nodes", "roads"}, "city_graph.json")
    if not isinstance(data["nodes"], list) or not data["nodes"] or not isinstance(data["roads"], list):
        raise ValueError("city_graph.json: expected a nonempty node list and a road list")
    nodes, roads, node_ids, road_keys = [], [], set(), set()
    for index, item in enumerate(data["nodes"]):
        context = f"city_graph.json node {index}"
        _fields(item, {"id", "name", "x", "y", "type"}, context)
        node_id = _text(item["id"], context)
        _unique(node_id, node_ids, context)
        nodes.append(Node(node_id, _text(item["name"], context),
                          _number(item["x"], context), _number(item["y"], context),
                          _text(item["type"], context)))
    for index, item in enumerate(data["roads"]):
        context = f"city_graph.json road {index}"
        _fields(item, {"from", "to", "distance", "speed", "road_type"}, context)
        source = _choice(item["from"], node_ids, context)
        target = _choice(item["to"], node_ids, context)
        _unique((source, target), road_keys, context)
        distance = _number(item["distance"], context, minimum=0)
        speed = _number(item["speed"], context, positive=True)
        if not isfinite(distance / speed):
            raise ValueError(f"{context}: travel time overflow")
        roads.append(Road(source, target, distance, speed, _text(item["road_type"], context)))

    responders, ids = [], set()
    columns = {"responder_id", "type", "start_location", "capabilities", "availability", "time_until_available"}
    for index, item in enumerate(read_csv(root / "responders.csv", columns=columns), 2):
        context = f"responders.csv record {index}"
        responder_id = _text(item["responder_id"], context)
        _unique(responder_id, ids, context)
        kind = _choice(item["type"], CAPABILITIES, context)
        capabilities = item["capabilities"].split(";")
        if len(set(capabilities)) != len(capabilities):
            raise ValueError(f"{context}: duplicate capabilities")
        for capability in capabilities:
            _choice(capability, CAPABILITIES[kind], context)
        availability = _choice(item["availability"], {"Available", "Busy"}, context)
        remaining = _number(item["time_until_available"], context, minimum=0)
        if availability == "Available" and remaining != 0:
            raise ValueError(f"{context}: Available responder must have zero remaining time")
        responders.append(Responder(responder_id, kind,
                                    _choice(item["start_location"], node_ids, context),
                                    frozenset(capabilities), availability, remaining))

    incidents, ids, warnings = [], set(), []
    all_capabilities = set().union(*CAPABILITIES.values())
    columns = {"incident_id", "location", "priority", "deadline", "required_capability", "timestamp", "time_required"}
    for index, item in enumerate(read_csv(root / "incidents.csv", columns=columns), 2):
        context = f"incidents.csv record {index}"
        incident_id = _text(item["incident_id"], context)
        _unique(incident_id, ids, context)
        incident = Incident(incident_id, _choice(item["location"], node_ids, context),
                            _choice(item["priority"], PRIORITIES, context),
                            _number(item["deadline"], context, minimum=0),
                            _choice(item["required_capability"], all_capabilities, context),
                            _number(item["timestamp"], context, minimum=0),
                            _number(item["time_required"], context, minimum=0))
        if incident.deadline < incident.timestamp:
            warnings.append(f"{incident.id}: deadline precedes release; cannot be handled on time")
        if not any(incident.required_capability in r.capabilities for r in responders):
            warnings.append(f"{incident.id}: no qualified responder in this scenario")
        incidents.append(incident)

    reports, report_ids, road_weather = [], set(), {}
    columns = {"from", "to", "weather", "source", "reported_status"}
    for index, item in enumerate(read_csv(root / "road_reports.csv", columns=columns), 2):
        context = f"road_reports.csv record {index}"
        road = _choice((item["from"], item["to"]), road_keys, context)
        source = _choice(item["source"], SOURCES, context)
        _unique((road, source), report_ids, context)
        weather = _choice(item["weather"], WEATHER, context)
        if road in road_weather and road_weather[road] != weather:
            raise ValueError(f"{context}: conflicting known weather for directed road {road}")
        road_weather[road] = weather
        reports.append(RoadReport(*road, weather, source,
                                  _choice(item["reported_status"], ROAD_STATUSES, context)))

    history, observation_ids = {}, set()
    columns = {"observation_nr", "from", "to", "traffic_observation"}
    for index, item in enumerate(read_csv(root / "observed_traffic.csv", columns=columns), 2):
        context = f"observed_traffic.csv record {index}"
        road = _choice((item["from"], item["to"]), road_keys, context)
        try:
            number = int(item["observation_nr"])
        except ValueError as error:
            raise ValueError(f"{context}: observation_nr must be a positive integer") from error
        if number < 1:
            raise ValueError(f"{context}: observation_nr must be positive")
        _unique((road, number), observation_ids, context)
        history.setdefault(road, []).append(TrafficObservation(number, *road,
            _choice(item["traffic_observation"], TRAFFIC_LEVELS, context)))
    history = {road: tuple(sorted(rows, key=lambda row: row.observation_nr)) for road, rows in history.items()}
    for road, rows in history.items():
        if [r.observation_nr for r in rows] != list(range(1, len(rows) + 1)):
            raise ValueError(f"observed_traffic.csv: noncontiguous sequence for {road}")
    if len(road_weather) < len(roads):
        warnings.append(f"{len(roads) - len(road_weather)} directed roads have no reports or known local weather")
    if len(history) < len(roads):
        warnings.append(f"{len(roads) - len(history)} directed roads have no traffic history")

    road_probabilities = read_json(root / "road_probabilities.json")
    traffic_probabilities = read_json(root / "traffic_probabilities.json")
    validate_road_probabilities(road_probabilities)
    validate_traffic_probabilities(traffic_probabilities)
    return Scenario(root.resolve(), tuple(nodes), tuple(roads), tuple(responders),
                    tuple(sorted(incidents, key=lambda incident: (incident.timestamp, incident.id))),
                    tuple(reports), history, road_probabilities, traffic_probabilities, tuple(warnings))
