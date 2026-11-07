# How to read the code

This guide describes the current implementation. For future traffic filtering and allocation decisions, read `DESIGN.md`. For exact input columns and matrix
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
The loader only validates tables; bayesian.py uses road CPTs afterward. HMM filtering remains deferred.

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
Traffic multipliers are not yet applied.

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

Read `TESTING.md` for coverage and limits. HMM filtering, OR-Tools allocation,
and standalone plan validation remain future work. Scripted event execution is described below.


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
not a replacement for the future CP-SAT allocator. Its author can know input;
the controller still checks that every dispatch occurs after actual revelation.

The result contains chronological commitments and processed event logs. Times
are deterministic modeled estimates, not guaranteed arrivals. The CLI adds
Bayesian blockage bounds per commitment without sampling actual road failures.
All functions and view classes document parameter meanings and pre/postconditions.
