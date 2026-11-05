# Actual scenario schemas and audit

Inspected all seven machine-readable files in each supplied scenario, plus
`Scenarios/README.md`. All three use the same schema. All probability rows are
finite, in [0,1], and sum to 1 within 1e-9; no renormalization is performed.

| Scenario | Nodes | Directed roads | Responders | Incidents | Reports | History roads | Observations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Scenario1 | 5 | 14 | 4 | 7 | 18 | 14 | 140 |
| Scenario2 | 12 | 30 | 10 | 12 | 42 | 3 | 15 |
| Scenario3 | 26 | 60 | 10 | 20 | 42 | 10 | 100 |

## Graph JSON

`city_graph.json` has `nodes` and `roads` arrays.

* Node: `id`, `name`, `x`, `y`, `type`.
* Road: `from`, `to`, `distance`, `road_type`, `speed`.

Coordinates and distances are metres, speed is metres/second. Base time is
distance/speed. Each listed road is one directed edge. All roads currently have
reverse entries; no duplicate directed endpoint pairs occur. Do not add extra
reverse edges. There is no explicit status, ground truth, or road ID field.

## CSV headers

Files are comma-delimited; capabilities use semicolons within a field.

```text
responders.csv
responder_id,type,start_location,capabilities,availability,time_until_available

incidents.csv
incident_id,location,priority,deadline,required_capability,timestamp,time_required

road_reports.csv
from,to,weather,source,reported_status

observed_traffic.csv
observation_nr,from,to,traffic_observation
```

Responder types: Ambulance, PoliceUnit, FireTruck. Capabilities are explicit
subsets of each type's assignment-listed capabilities; do not assign all
capabilities automatically from type. Availability is Available/Busy. Scenario1
R4 is Busy for 10 seconds; all other supplied responders start Available.

Incident priority: Critical/High/Medium/Low. All supplied deadlines are at or
after release. Release ranges: 0-60, 0-60 and 0-5000 seconds respectively.
No supplied incident has a capability absent from the responder pool. That does
not prove it can be scheduled under deadlines and resource contention.

Report sources: Citizen, Police, Sensor. Weather: Clear/Rain/Storm. Reported
statuses: Open/Congested/Blocked. Reports have **no timestamp**, are known at t=0,
and weather belongs to their directed road. There are 3 reports per covered road:
6 covered roads in Scenario1, 14 in Scenario2, 14 in Scenario3. Respectively
8, 16 and 46 directed roads have no reports or local weather. No covered road has
conflicting weather or duplicate report sources. Opposite directions are separate.

Traffic observations use Low/Medium/High. `observation_nr` restarts at 1 for
each directed road, and is not simulation time. Scenario1 has 10 observations
on all 14 roads; Scenario2 has 5 on 3 roads; Scenario3 has 10 on 10 roads.
Histories are complete contiguous ordinal sequences where present; missing
history is allowed. There are 0, 27 and 50 roads without history respectively.
No sampling interval or physical historical timestamps are provided.

## Bayesian JSON

`road_probabilities.json`:

| Field | Outer key | Inner key/value |
| --- | --- | --- |
| weather_prior | Weather | Probability |
| road_status_given_weather | Weather | Status -> probability |
| citizen_report | True status | Reported status -> probability |
| police_report | True status | Reported status -> probability |
| sensor_report | True status | Reported status -> probability |

The report tables are interpreted as P(reported status | true status), matching
the assignment's conditional direction and normalized rows. Do not transpose
them during inference. For example Sensor row Blocked is {Open:0.03,
Congested:0.07, Blocked:0.90} in Scenario1.

## Traffic JSON

`traffic_probabilities.json` contains:

* `initial[state]`.
* `transition[current_state][next_state]`.
* `emission[hidden_state][observed_level]`.

All states/observation labels are Low/Medium/High; rows normalize to 1.
This is the standard row-conditional interpretation used in the design. Numeric
normalization alone cannot establish temporal alignment; first-observation and
time-step conventions are explicitly documented in `DESIGN.md`.

## Validation policy

Readers preserve string IDs and reject duplicate JSON keys, NaN/Infinity, bad
CSV widths and duplicate headers. Typed loading validates exact expected fields,
unique IDs/roads, graph references, finite numeric ranges, positive speed,
capabilities, labels, availability consistency, probability labels/ranges/sums,
conflicting weather, duplicate reports and historical indices. CSV column order
is flexible, but column names must match.

Unsorted histories are sorted per road. Duplicate or gapped historical indices
are rejected because the data defines an ordinal sequence and supplies no time
interval to explain gaps. Fractional time fields are preserved. Missing evidence,
impossible deadlines and absent qualified responders produce warnings rather
than aborting an otherwise structurally valid scenario.
