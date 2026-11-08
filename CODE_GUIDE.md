# How to read the code

This guide describes the current implementation. For traffic integration decisions and extensions, read `DESIGN.md`. For exact input columns and matrix
layouts, read `DATA_SCHEMA.md`.

## Follow one run

```console
python run.py Scenarios/Scenario1 --route H1 N2
```

1. `run.py:main` reads the scenario directory and optional route endpoints.
2. `loaders.py:load_scenario` reads all seven files, checks them and returns a
   `Scenario`. The loader validates tables; run.py then calls Bayesian inference separately.
3. `routing.py:build_graph` constructs a new graph. This CLI call supplies no
   statuses, so every road uses its normal all-open travel time.
4. `search.py:ucs` finds a cheapest directed path from H1 to N2.
5. `run.py` prints a JSON summary and route. It does not assign a responder or
   produce the final assignment's plan/statistics files.

The result is a direct H1 -> N2 route taking approximately 48.067 seconds under
normal conditions. This is a routing example, not a claim that noisy reports
say that road is open.

## Reading parameter descriptions and contracts

Each class/function/method docstring now describes its parameters and has
`Preconditions` and `Postconditions` sections:

* **Parameters:** what each argument means, its expected shape and relevant units.
  In a data class these describe the generated constructor's fields. Python passes
  `self` automatically when you call a method on an object.
* **Preconditions:** what must hold for the documented operation. The text states
  which conditions the implementation checks and which remain the caller's
  responsibility. Documentation does not add assertions or new runtime checks.
* **Postconditions:** what holds after successful completion, including the return
  value and any state changes. If failure is the only outcome, this is explicit.
  A raised exception does not imply that successful-return postconditions hold.

For example, `Graph.add_edge` requires existing endpoints and finite nonnegative
seconds. These are checked before insertion. Success appends exactly one directed
edge, with no automatic reverse edge. In contrast, a directly constructed `Road`
does not validate its fields; use the loader to obtain validated scenario records.

See `ucs` for algorithm assumptions: costs stay fixed during search, and cumulative
costs must remain representable as finite floating-point values. Passing the normal
scenario checks alone is not a proof against overflow for arbitrary huge inputs.

## Input records: models.py

A dataclass groups related fields into a named Python object. For example,
`incident.deadline` is easier to explain than an unnamed array position.
`frozen=True` prevents assigning a new value to a field; it does not make nested
dictionaries deeply immutable. Treat all loaded data as read-only.

| Record | Meaning |
| --- | --- |
| Node | A location with an ID and coordinates in metres. |
| Road | A directed connection with distance and normal speed. |
| Responder | Initial location, explicit capabilities and initial availability. |
| Incident | Release timestamp, absolute arrival deadline and service duration. |
| RoadReport | Noisy Citizen/Police/Sensor evidence plus local known weather. |
| TrafficObservation | One ordinal observation in a directed road's historical sequence. |
| Scenario | All validated input records, model tables and nonfatal warnings. |

`Road.key` returns `(source, target)` for joining a road to its reports/history.
`Road.id` derives a readable edge label because the input has no explicit road ID.
`Road.normal_seconds` divides metres by metres/second. No unit conversion factor
is needed.

`Responder.initial_ready_at` only describes availability relative to time zero.
It does not update when a future simulation dispatches the responder.
`Scenario.known_incidents(now)` restricts input to incidents already released;
it does not know which incidents have been completed or assigned.

## Input checks: loaders.py

The raw readers handle file syntax; the scenario loader interprets domain data.
This separation keeps string IDs intact and prevents accidentally converting
labels or capabilities into numbers.

Helper functions start with `_` to signal internal use:

| Helper | Why it exists |
| --- | --- |
| `_unique_object` / `_invalid_constant` | Reject ambiguous JSON keys and nonstandard NaN/Infinity constants. |
| `_fields` | Require the expected object keys. |
| `_text` | Check nonempty text without silently trimming identifiers. |
| `_number` | Convert numeric text, preserve fractions, and check finite values/bounds. |
| `_choice` | Check a label or reference against allowed values. |
| `_unique` | Detect duplicate identifiers instead of overwriting records. |
| `_distribution` / `_matrix` | Check probability labels, ranges and row sums without repairing inputs. |

`load_scenario` is organized into seven commented steps: nodes, roads,
responders, incidents, reports, traffic history and model parameters. Loading
nodes/roads first allows later location and evidence references to be checked.

Structural contradictions stop loading. Missing evidence and obviously infeasible
incidents produce warnings. For example, a deadline before release is a real
scenario problem that should remain visible, rather than being changed silently.

Traffic history is grouped by directed road and sorted by `observation_nr`.
Those indices never enter the incident release-time calculation. Bayesian report
tables use `table[true_status][reported_status]`; HMM transition tables use
`transition[current][next]`, and emissions use `emission[hidden][observed]`.
The loader only validates tables; bayesian.py uses road CPTs afterward and hmm.py
uses the traffic tables in independent Forward filtering.

## Graph and routing policy: graph.py and routing.py

The graph is an adjacency list: each source node maps to a list of outgoing
`Edge` objects. An edge stores destination, road identity and fixed seconds.
There is no automatic reverse edge. A tuple returned by `neighbors` protects
the internal list from accidental modification by callers.

`build_graph` is the adapter between scenario records and that generic graph:

* No status mapping: explicit all-open normal-speed baseline.
* Complete status mapping: Open uses normal time, Congested multiplies by 1.5,
  and Blocked is omitted entirely.

It requires complete mappings so an omitted road does not silently become Open.
It creates a new graph without changing the scenario. This explicit-label
adapter remains for baseline/tests. Bayesian integration instead calls
build_bayesian_graph with full distributions; it does not reduce them to labels.
Traffic multipliers are deliberately not applied; traffic exposure is separate.

## Uniform-cost search: search.py

The algorithm follows the course's UCS rule: expand the frontier entry with the
smallest accumulated path cost `g(n)`.

| Variable | Meaning |
| --- | --- |
| `frontier` | Min-heap of `(cost, tie_counter, node)` entries awaiting exploration. |
| `serial` | Counter that makes equal-cost expansion order follow discovery order. |
| `best` | Cheapest discovered cost for each reached node. |
| `parent` | Predecessor node and selected road used for path reconstruction. |
| `candidate` | Cost of reaching a neighbor through the current node. |

When a cheaper route is found, a new heap entry is added. The previous entry
remains in the heap but is skipped when removed because it no longer matches
`best`. This avoids needing an in-place heap priority update.

Finding a goal among the neighbors is not enough to finish: another frontier
path may still be cheaper. The algorithm accepts the goal when its current best
entry is popped. It then walks backwards through `parent` and reverses the path.
Only strictly cheaper candidates are added, preventing equal-cost zero cycles
from repeating forever.

`Route.seconds` includes travel only. Absolute arrival would require adding
departure time; response time would additionally compare arrival to release.
Neither responder scheduling nor those plan calculations occur in UCS.

If the frontier empties, the function returns `None`. Start equals goal returns
a single-node path, no roads and zero seconds. Optimality assumes a finite graph
and fixed nonnegative costs; it does not establish true-world road accessibility.

## Tests and further reading

`tests/test_foundation.py` uses tiny graphs with hand-checkable answers.
`tests/test_scenarios.py` checks the actual data, status effects, and 845 ordered
node pairs against independent Bellman-Ford relaxation. It also corrupts temporary
copies to verify rejection/warning behavior without editing the supplied inputs.

```console
python -m unittest discover -s tests -v
```

Read TESTING.md for coverage and limits. Automatic/scripted execution, required
exports and standalone original-data validation are described below.


## Bayesian reasoning and probability-aware routing

`bayesian.infer_road_status(probabilities, weather=..., reports=...)` computes a
full Open/Congested/Blocked distribution for one road. It multiplies prior and
source-specific likelihoods, then normalizes. Unknown weather is summed out;
missing report variables contribute one. `infer_scenario` groups evidence per
directed road and returns a distribution for every road, including unreported
ones. Nothing chooses routes or asserts a true status in this module.

`risk_routing.build_bayesian_graph(scenario, beliefs, blocked_threshold=...)`
requires an explicit threshold, removes roads whose blockage probability reaches
it, and assigns conditional expected traversal seconds to accepted edges. UCS
optimizes that fixed score. `route_blockage_bounds` separately reports lower/upper
bounds for encountering any blocked road, without assuming independent roads.

Run the README's Bayesian CLI example to see all distributions, the selected
policy, a route, conditional travel score and blockage bounds. An unreachable
route prints null instead of weakening the threshold silently. The bounds can
exceed the threshold because an edge limit is not a route-level risk constraint.
The code does not claim to choose the safest route or unconditional arrival time.
New test modules check inference arithmetic, marginalization, policy limitations,
all-pairs UCS integration and CLI behavior. See DESIGN.md for the equations.


## Simulation: inputs, controller, decisions and results

`simulate(scenario, graph, dispatcher, strict_deadlines=True, decision_times=())`
creates isolated dynamic state and a private graph snapshot. Its event heap jumps
directly to relevant times. Releases, initial availability, arrivals and completions
at one timestamp are applied before dispatch. Immediate zero-duration event chains
settle before finalizing deadline misses. Met deadlines are not allowed to expire
ongoing treatment, and obsolete deadline events do not extend the run.

`simulation_models.py` defines frozen snapshots/requests/candidates/results. The
dispatcher receives DecisionSnapshot only: revealed incident views, responder
state, current candidates, clock and deadline policy. It never receives Scenario
or the future event queue. It returns AssignmentRequest IDs; the engine validates
the whole batch and commits fixed routes, departures, arrivals and completions.
No callback can reserve an unavailable responder or dispatch an unreleased incident
through this interface. Already committed assignments cannot be changed.

Responder location is None while travelling; arrival sets the incident node and
starts treatment. Completion leaves it there and makes it available at exactly
that time. Initially busy responders are released at their supplied start node;
no nonexistent initial incident is invented. Original input records stay frozen.

Incident status (pending/travelling/treating/completed/closed_unassigned) and
deadline_result (not_due/met/missed) answer different questions. Strict mode closes
pending work after its deadline. Late mode keeps it eligible and can produce
completed+missed, closing only remaining unassigned work when no events remain.

`scripted.py` reads JSON fixtures and consumes each timestamp once. Pass its
decision_times as explicit controller wake-ups. A script is for testing execution,
not a replacement for the CP-SAT allocator. Its author can know input;
the controller still checks that every dispatch occurs after actual revelation.

The result contains chronological commitments and processed event logs. Times
are deterministic modeled estimates, not guaranteed arrivals. The CLI adds
Bayesian blockage bounds per commitment without sampling actual road failures.
All functions and view classes document parameter meanings and pre/postconditions.


## Online allocation: allocation.py

CspDispatcher(snapshot) builds a fresh Boolean model from current candidates only.
x[r,i] selects one pair; y[i]=sum_r x[r,i] is Boolean, so at most one responder
handles an incident. Responder sums <=1 prevent double booking. Missing pairs
have no variable. Optional unassignment makes all-zero feasible but priority
coverage objectives ensure it cannot win merely by having zero response cost.

Sequential objectives maximize Critical/High/Medium/Low counts, then on-time counts
in that order only when late responses are allowed, then minimize ceil-millisecond
response (arrival-release). No deadline/urgency ranking or waiting-age bonus exists.
Only proven optimum values become equality constraints for later phases. Execution
times remain unrounded. Per-phase solver statuses, bounds and elapsed solver time
are recorded in diagnostics; FEASIBLE/UNKNOWN/budget exhaustion never masquerade
as proven hierarchy optimality. No future inputs are loaded or passed in.

NearestDispatcher uses the same candidates, sorted by travel and stable IDs,
greedily avoiding used responders/incidents. It provides an intentionally simple
comparison, not a guaranteed best matching. statistics.summarize reports completed
count, independent met count, all/handled percentages and mean response over
completed work (None when empty). run.py defaults to CSP, with nearest, script,
route and comparison options. benchmark.py repeats the controlled evaluation.

Inspect TESTING.md and results/allocation_comparison.json for observed results.
In Scenario3, different equal-cost initial unit placements affect future calls;
CP-SAT's local optimum does not prove a globally best emergency-response sequence.

## Historical HMM and traffic routing

`hmm.forward_filter(tables, observations)` is the mathematical layer. It starts
from the supplied prior, applies the first emission, then repeats transition
prediction and emission reweighting/normalization. It returns all three states.
`hmm.infer_traffic(scenario)` sorts/validates each directed history, calls Forward
once per road and returns TrafficBelief records including observation_count and
prior_only. No histories means that scenario's prior, not assumed Low traffic.
These functions know nothing about graph costs, dispatches or simulation time.

`TrafficRouter(roads, beliefs, ...)` is the independent policy layer. Its startup
copies of normal_seconds*P(High) weights use directed road IDs. `exposure(route)`
adds these scores without interpreting them as time. `_shortest` is a handwritten
UCS with (travel,exposure) queue costs. `_bounded` keeps nondominated time/score
labels rather than one cost per node, under an explicit travel-time resource cap.
The call method first computes a shortest reference, bounds permitted travel,
and checks the configured minimum relative exposure reduction. `describe` reports
actual score, shortest reference time/score, extra seconds and relative reduction.
The label guard raises visibly on excessive search, rather than claiming success.

`simulate(..., route_planner=None)` preserves original scalar UCS by default.
With a TrafficRouter it supplies graph/current endpoints/strict remaining duration
only. `_check_route` verifies shape, directed edges and graph-duration sum. The
simulator still calculates arrivals and completion using route.seconds, and
availability still includes treatment. Neither exposure nor HMM probabilities
reach the CP-SAT objective. Strict mode refuses detours past the deadline; late
mode permits them and records the resulting deadline outcome independently.

`run.py --traffic-policy hmm-tie|hmm-bounded` opts into these preferences with
Bayesian routing. Bounded mode needs an explicit --max-extra-fraction, with
--min-exposure-reduction default .10. Default bayesian-only preserves previous
UCS behavior. JSON reports full traffic beliefs/provenance and separates traffic
scores from route.seconds and route blockage bounds. `benchmark_traffic.py` runs
all three policies with both allocators/deadline modes and audits all endpoint
pairs. Full fixed-parameter results are in results/traffic_comparison.json.

## Required files and independent replay

`outputs.make_plan(result)` copies each AssignmentRecord's responder/incident IDs,
route.nodes and departure_time to exactly the assignment's list/row schema.
`write_outputs` invokes independent validation, checks replay travel/arrival/
completion against records and independent statistics against summarize(result),
then writes plan.json and statistics.txt. It performs no new allocation/routing
or scheduling. render_statistics adds definitions, units, unhandled IDs, validity
and settings to the existing metrics. Empty means/denominators are N/A.

`plan_validation.load_plan(path)` rejects malformed JSON, duplicate keys and
NaN/Infinity. `validate_plan(original_scenario, decoded_plan, ...)` checks schema,
IDs, capability, releases, readiness/previous completion, current location,
directed original roads, Bayesian edge filtering/cost and arrival deadlines.
It sorts by start time, retaining input order for same-time zero-duration jobs.
Travel and treatment are reconstructed from original inputs, not exported claims.
It shares Bayesian inference and a statistics dataclass but no simulator/search/
graph builder/summarize implementation. Structured errors name row and constraint.

`PlanValidation.valid` is relative to declared routing/deadline policy.
`deadline_compliant` additionally requires every assigned arrival to be on time;
it does not claim all incidents were handled. Unhandled IDs/metrics show coverage.
Invalid plans have statistics=None. A valid empty plan can still perform poorly.
The standalone validate_plan.py prints this report and exits0/1/2 for policy-valid,
invalid plan or file/configuration error; it does not need OR-Tools or replan.

run.py normal/script runs export by default to the current directory; --output-dir
selects another destination, and --compare uses separate csp/nearest subdirectories.
--route is diagnostic and produces no assignment files. stdout retains the richer
simulation JSON with output paths/validation. Existing routing/allocator defaults
remain unchanged; README has an explicit Bayesian+HMM full-system command.
