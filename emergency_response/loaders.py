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
    """Build a JSON object while rejecting duplicate keys at any nesting level.

    json.load calls this hook with the original key/value pairs. A plain dictionary
    would otherwise overwrite duplicate keys before validation could notice them.

    Parameters:
        pairs: Iterable of (string key, parsed value) pairs supplied by json.load for
            one object.

    Preconditions:
        Entries must be two-item pairs with hashable keys; JSON supplies string keys.
        Repeated keys are checked.

    Postconditions:
        Returns a new dict containing every supplied key/value exactly once, or raises
        ValueError for a duplicate. Does not modify parsed values; consumes the
        iterable.
    """
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    """Reject JSON extensions NaN/Infinity that cannot represent valid inputs.

    Parameters:
        value: Text token passed by json.load, such as 'NaN', 'Infinity' or
            '-Infinity'.

    Preconditions:
        Intended as json.load's parse_constant callback; no special input constraints
        are checked.

    Postconditions:
        There is no successful return: always raises ValueError identifying the token.
        No external state changes.
    """
    raise ValueError(f"Nonstandard JSON constant: {value}")


def read_json(path):
    """Read UTF-8 JSON, allowing a BOM but rejecting duplicate keys and constants.

    Returns the parsed structure without interpreting its schema. Typed validation
    is performed by load_scenario. File and JSON parsing errors propagate to callers.

    Parameters:
        path: str or pathlib-compatible path to the UTF-8 JSON file to read.

    Preconditions:
        path must be path-like and readable; filesystem errors propagate. JSON syntax,
        duplicate object keys and explicit NaN/Infinity constants are checked during
        parsing. Domain schema checks happen later.

    Postconditions:
        Returns a parsed JSON value, possibly an object, array or scalar. Does not
        change the source file and closes it on success or failure. Does not guarantee
        domain validity or finite numeric literals that overflow during standard JSON
        parsing.
    """
    with Path(path).open(encoding="utf-8-sig") as stream:
        return json.load(stream, object_pairs_hook=_unique_object,
                         parse_constant=_invalid_constant)


def read_csv(path, *, delimiter=",", columns=None):
    """Read CSV records as dictionaries, preserving every cell as text.

    delimiter defaults to comma; optional columns checks the exact set of headers,
    independent of column order. UTF-8 BOMs and quoted separators are supported.
    Identifiers such as '001' are preserved; conversion belongs in typed loading.
    Empty/duplicate headers or mismatched record widths raise ValueError. CSV syntax
    and filesystem errors propagate. Record numbers identify logical CSV records,
    not necessarily physical lines when quoted values span multiple lines.

    Parameters:
        path: str or pathlib-compatible path to a UTF-8 CSV file.
        delimiter: Single-character field separator accepted by csv.DictReader;
            defaults to comma.
        columns: Optional iterable of expected unique column names. None skips
            expected-name comparison; header presence/uniqueness is still checked.

    Preconditions:
        path must be readable, delimiter must be a valid CSV delimiter, and columns (if
        supplied) must contain hashable names. Header presence/uniqueness, optional
        exact header set, and record widths are checked. Values are not domain-
        validated.

    Postconditions:
        Returns a list of dicts mapping header strings to cell strings in file order.
        IDs and fractions are not converted. A header-only file returns an empty list.
        The file is unchanged and closed, including on parsing failure.
    """
    # newline="" lets the CSV parser handle quoted newlines and platform line endings.
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=delimiter, strict=True)
        headers = reader.fieldnames
        if not headers or any(not h for h in headers) or len(set(headers)) != len(headers):
            raise ValueError(f"{path}: CSV needs nonempty, unique column names")
        if columns is not None and set(headers) != set(columns):
            raise ValueError(f"{path}: expected columns {sorted(columns)}, got {headers}")
        rows = []
        for line, row in enumerate(reader, start=2):
            # DictReader uses a None key for extra cells and None values for missing cells.
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{path}: CSV row width differs from header at record {line}")
            rows.append(row)
        return rows


def _fields(value, expected, context):
    """Require a dictionary with exactly the expected keys; report its context.

    Parameters:
        value: Candidate parsed object whose keys need checking.
        expected: Iterable of expected hashable keys; treated as a set.
        context: Human-readable location included in errors, such as a filename/record
            number.

    Preconditions:
        expected must be iterable with hashable keys. Object type and exact key set are
        checked; no nested values are checked here.

    Postconditions:
        Returns None if value is a dict with exactly the expected keys; otherwise
        raises ValueError. Inputs remain unchanged.
    """
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f"{context}: expected fields {sorted(expected)}")


def _text(value, context):
    """Return nonempty text, rejecting surrounding whitespace rather than trimming IDs.

    Parameters:
        value: Candidate text field from parsed input.
        context: Human-readable field/record location for errors.

    Preconditions:
        No string validity is assumed: string type, nonempty content and absence of
        surrounding whitespace are checked.

    Postconditions:
        Returns the original string unchanged if valid, otherwise raises ValueError.
        Does not trim or modify text.
    """
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{context}: expected nonempty text without surrounding whitespace")
    return value


def _number(value, context, *, minimum=None, positive=False):
    """Convert a CSV string or JSON number to a finite float with optional bounds.

    minimum is inclusive; positive requires a value strictly greater than zero.
    Boolean values are rejected even though Python considers them integers.
    Fractional seconds remain fractional; no rounding or unit conversion occurs.

    Parameters:
        value: CSV numeric string or JSON int/float to convert; bool is rejected.
        context: Human-readable field/record location for errors.
        minimum: Optional inclusive numeric lower bound; None disables this bound.
        positive: If True, also require the result to be strictly greater than zero;
            defaults to False.

    Preconditions:
        minimum must be None or a suitable numeric bound, and positive should be bool
        (caller assumptions). Input type, conversion, finiteness, and requested bounds
        are checked.

    Postconditions:
        Returns a finite float satisfying minimum and/or positivity, or raises
        ValueError for checked invalid input. Preserves fractional values within
        floating-point precision; inputs are unchanged.
    """
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
    """Return a value only if it belongs to the supplied labels or reference IDs.

    Parameters:
        value: Candidate label, node ID or road endpoint pair.
        choices: Allowed membership collection, normally a set or dict whose keys are
            choices.
        context: Human-readable field/record location for errors.

    Preconditions:
        value must support membership in choices; for sets/dicts it must be hashable.
        Choices should be mutually sortable for the error message. Membership is
        checked.

    Postconditions:
        Returns value unchanged if allowed, otherwise raises ValueError for a normal
        invalid choice. Does not modify the collection.
    """
    if value not in choices:
        raise ValueError(f"{context}: {value!r} must be one of {sorted(choices)}")
    return value


def _unique(value, seen, context):
    """Record a hashable identifier in seen, raising ValueError if already present.

    Parameters:
        value: Hashable identifier or compound key to register.
        seen: Mutable set of identifiers already encountered in the current input
            scope.
        context: Human-readable field/record location for errors.

    Preconditions:
        value must be hashable and seen must support membership/add. Duplicate
        membership is checked.

    Postconditions:
        On success returns None and adds value to seen; all previous members remain. On
        a duplicate raises ValueError without changing seen.
    """
    if value in seen:
        raise ValueError(f"{context}: duplicate {value!r}")
    seen.add(value)


def _distribution(value, labels, context):
    """Validate one labelled probability row without modifying or normalizing it.

    Require exactly the expected labels, numeric finite probabilities in [0,1], and
    a sum within absolute tolerance 1e-9 of one. This tolerance allows small decimal
    representation errors; it is not permission to repair malformed probability data.

    Parameters:
        value: Candidate dict mapping labels to numeric probabilities.
        labels: Expected probability labels, for example ROAD_STATUSES or
            TRAFFIC_LEVELS.
        context: Table/row location used in validation errors.

    Preconditions:
        labels must be iterable and hashable. Dict keys, non-boolean numeric
        probabilities, finiteness, [0,1] bounds and sum-to-one tolerance 1e-9 are
        checked.

    Postconditions:
        Returns None only if all distribution checks pass; otherwise raises ValueError
        for checked invalid data. The table is unchanged and is never renormalized.
    """
    _fields(value, labels, context)
    for label, probability in value.items():
        if isinstance(probability, bool) or not isinstance(probability, (int, float)):
            raise ValueError(f"{context}.{label}: probability must be numeric")
        if not isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError(f"{context}.{label}: probability outside [0, 1]")
    if not isclose(sum(value.values()), 1.0, rel_tol=0, abs_tol=1e-9):
        raise ValueError(f"{context}: probabilities must sum to 1")


def _matrix(value, outer, inner, context):
    """Validate outer condition labels and each inner conditional probability row.

    Parameters:
        value: Candidate nested dict: condition label -> probability row.
        outer: Expected outer condition labels, such as current hidden states.
        inner: Expected outcome labels in each row, such as next hidden states.
        context: Name/location of the conditional table for errors.

    Preconditions:
        outer and inner must be usable as label sets. Exact outer keys and each inner
        distribution are checked.

    Postconditions:
        Returns None only if every expected conditional row is valid; otherwise raises
        ValueError. Does not transpose, repair or normalize rows.
    """
    _fields(value, outer, context)
    for label in outer:
        _distribution(value[label], inner, f"{context}.{label}")


def validate_road_probabilities(data):
    """Check the Bayesian input tables, without computing a posterior.

    Rows are P(status|weather) and, for each source, P(report|true status).
    Weather prior is retained for roads whose local weather is unknown.
    Valid structure does not establish that different reports are independent;
    that remains an explicit assumption for the future inference component.

    Parameters:
        data: Parsed road_probabilities.json object containing weather prior, status-
            given-weather and three source report tables.

    Preconditions:
        No domain validity is assumed. Top-level keys, required state labels,
        probability ranges and row sums are checked.

    Postconditions:
        Returns None if the supplied Bayesian table schema is valid, otherwise raises
        ValueError for checked invalid data. No tables change and no
        posterior/independence claim is computed.
    """
    _fields(data, {"weather_prior", "road_status_given_weather", *SOURCES.values()}, "road_probabilities.json")
    _distribution(data["weather_prior"], WEATHER, "weather_prior")
    _matrix(data["road_status_given_weather"], WEATHER, ROAD_STATUSES, "road_status_given_weather")
    for table in SOURCES.values():
        # Outer: true status. Inner: reported status. P(report | true status).
        _matrix(data[table], ROAD_STATUSES, ROAD_STATUSES, table)


def validate_traffic_probabilities(data):
    """Check HMM tables using traffic labels, without filtering observations.

    initial[state], transition[current][next] and emission[hidden][observed] use
    Low/Medium/High. Road accessibility labels are a separate state space.
    Rows must normalize; this cannot determine a real-world sampling interval.

    Parameters:
        data: Parsed traffic_probabilities.json object with initial, transition and
            emission tables over Low/Medium/High.

    Preconditions:
        No domain validity is assumed. Top-level keys, traffic labels, probability
        ranges and row sums are checked.

    Postconditions:
        Returns None if the supplied HMM table schema is valid, otherwise raises
        ValueError for checked invalid data. No beliefs are filtered and no physical
        sampling interval is inferred; input is unchanged.
    """
    _fields(data, {"initial", "transition", "emission"}, "traffic_probabilities.json")
    _distribution(data["initial"], TRAFFIC_LEVELS, "initial")
    # transition[current][next]; emission[hidden][observed].
    for table in ("transition", "emission"):
        _matrix(data[table], TRAFFIC_LEVELS, TRAFFIC_LEVELS, table)


def load_scenario(directory) -> Scenario:
    """Load all seven input files from one Scenarios/ScenarioN directory.

    Returns a typed Scenario with directed roads, all incident input records,
    source-specific road reports, sorted per-road traffic histories, validated
    probability tables, and warnings. Units follow Scenarios/README.md: metres,
    metres/second, and seconds. No inference, allocation or simulation is performed.

    Structural errors (for example duplicate IDs, unknown roads, inconsistent
    availability or invalid probability rows) stop loading. Missing evidence and
    obvious incident infeasibility are retained as warnings so valid data remains
    inspectable. Busy with zero remaining duration is allowed as ready at time zero.

    The future planner must use Scenario.known_incidents(now); merely parsing future
    records must not influence dispatch before release. Input records and probability
    tables should be treated as read-only after loading.

    Raises:
        ValueError: A schema, reference, range or consistency check fails.
        OSError: A required input file cannot be read.
        csv.Error: Input contains malformed CSV syntax.

    Parameters:
        directory: str or pathlib-compatible directory containing the seven expected
            ScenarioN input files.

    Preconditions:
        directory must be accessible and contain the required readable UTF-8 files.
        Caller interprets units according to Scenarios/README.md (metres,
        metres/second, seconds); units cannot be deduced from numeric cells.
        Structural/domain checks run before a Scenario is returned.

    Postconditions:
        Returns a Scenario with unique referenced nodes/roads/responders/incidents,
        valid labels/ranges, sorted contiguous per-road histories, validated
        probability rows, and warnings for missing evidence or obvious incident
        infeasibility. Incidents are ordered by (timestamp,id), including future
        records. Input files are unchanged and opened handles are closed. Does not
        guarantee schedulability, infer hidden states, or release future incidents.
    """
    # 1. Load nodes first so every later location/road reference can be checked.
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
    # 2. Preserve each directed road; the source file already lists reverse arcs.
    for index, item in enumerate(data["roads"]):
        context = f"city_graph.json road {index}"
        _fields(item, {"from", "to", "distance", "speed", "road_type"}, context)
        source = _choice(item["from"], node_ids, context)
        target = _choice(item["to"], node_ids, context)
        # No source road IDs exist, so duplicate endpoints would make evidence ambiguous.
        _unique((source, target), road_keys, context)
        distance = _number(item["distance"], context, minimum=0)
        speed = _number(item["speed"], context, positive=True)
        if not isfinite(distance / speed):
            raise ValueError(f"{context}: travel time overflow")
        roads.append(Road(source, target, distance, speed, _text(item["road_type"], context)))

    # 3. Parse initial responder state; do not expand capabilities from type alone.
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

    # 4. Parse the incident stream, retaining future records without releasing them.
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
        # Structurally valid but infeasible incidents should remain visible in the audit.
        if incident.deadline < incident.timestamp:
            warnings.append(f"{incident.id}: deadline precedes release; cannot be handled on time")
        if not any(incident.required_capability in r.capabilities for r in responders):
            warnings.append(f"{incident.id}: no qualified responder in this scenario")
        incidents.append(incident)

    # 5. Reports are time-zero evidence with known weather local to their directed road.
    reports, report_ids, road_weather = [], set(), {}
    columns = {"from", "to", "weather", "source", "reported_status"}
    for index, item in enumerate(read_csv(root / "road_reports.csv", columns=columns), 2):
        context = f"road_reports.csv record {index}"
        road = _choice((item["from"], item["to"]), road_keys, context)
        source = _choice(item["source"], SOURCES, context)
        # Without report IDs/timestamps, repeated source rows cannot be disambiguated.
        _unique((road, source), report_ids, context)
        weather = _choice(item["weather"], WEATHER, context)
        if road in road_weather and road_weather[road] != weather:
            raise ValueError(f"{context}: conflicting known weather for directed road {road}")
        road_weather[road] = weather
        reports.append(RoadReport(*road, weather, source,
                                  _choice(item["reported_status"], ROAD_STATUSES, context)))

    # 6. Group pre-simulation traffic history by directed road, not by simulation time.
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
    # Input row order is irrelevant; observation_nr supplies the sequence order.
    history = {road: tuple(sorted(rows, key=lambda row: row.observation_nr)) for road, rows in history.items()}
    for road, rows in history.items():
        # No sampling interval is supplied to justify interpreting missing steps.
        if [r.observation_nr for r in rows] != list(range(1, len(rows) + 1)):
            raise ValueError(f"observed_traffic.csv: noncontiguous sequence for {road}")
    # Missing coverage is expected in these scenarios; warn instead of inventing evidence.
    if len(road_weather) < len(roads):
        warnings.append(f"{len(roads) - len(road_weather)} directed roads have no reports or known local weather")
    if len(history) < len(roads):
        warnings.append(f"{len(roads) - len(history)} directed roads have no traffic history")

    # 7. Validate model parameters only. Posterior inference/filtering comes later.
    road_probabilities = read_json(root / "road_probabilities.json")
    traffic_probabilities = read_json(root / "traffic_probabilities.json")
    validate_road_probabilities(road_probabilities)
    validate_traffic_probabilities(traffic_probabilities)
    # Return stable input records; timestamp sorting does not expose incidents early.
    return Scenario(root.resolve(), tuple(nodes), tuple(roads), tuple(responders),
                    tuple(sorted(incidents, key=lambda incident: (incident.timestamp, incident.id))),
                    tuple(reports), history, road_probabilities, traffic_probabilities, tuple(warnings))
