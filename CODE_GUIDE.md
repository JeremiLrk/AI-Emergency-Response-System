# Follow the code from start to finish

Read this guide to find the code behind a run. [DESIGN.md](DESIGN.md) explains the choices and calculations. [DATA_SCHEMA.md](DATA_SCHEMA.md) lists the exact input fields.

## Start with one run

Run `python run.py` and pick a scenario. The menu uses Bayesian road estimates, bounded HMM routing, CP-SAT allocation and strict deadlines. It prints the plan and statistics and saves them under `results/menu/ScenarioN/`.

To see search on its own, try:

```console
python run.py Scenarios/Scenario1 --route H1 N2
```

`run.py:main` reads the arguments and calls `load_scenario` to check the seven files. Inference runs separately from loading. This explicit command builds the all-open graph with `routing.build_graph`, then asks `search.ucs` for a path from H1 to N2. It prints diagnostic JSON with a direct route of about 48.067 seconds at normal speed. Route mode performs no dispatch and writes neither assignment file. This example assumes open roads for comparison.

## Read a function's documentation

- **Parameters** tell you what to pass, its shape and units. On a dataclass, these describe the constructor fields. Python supplies `self` when you call a method on an object.
- **Preconditions** describe what must be true before the call. Some are checked by the function and others are the caller's responsibility. A docstring adds no runtime checks by itself.
- **Postconditions** describe the result and state changes after success. A raised error does not promise those results. The docs say when an error is the only possible outcome.

For example, `Graph.add_edge` checks that both nodes exist and that seconds are finite and nonnegative. It adds one directed edge. A `Road` created directly does not check its fields, so use the loader for validated input. UCS also assumes costs are fixed and their sums fit in a finite float. Extremely large values can overflow even when each input value is finite.

## Input records in models.py

A dataclass groups named fields, such as `incident.deadline`. `frozen=True` prevents replacing a field, but a dictionary stored inside it can still be changed. Treat loaded inputs as read-only.

| Record | What it contains |
| --- | --- |
| `Node` | Location ID and coordinates in metres. |
| `Road` | Directed endpoints, distance and normal speed. |
| `Responder` | Start node, explicit skills and starting availability. |
| `Incident` | Release time, absolute arrival deadline and treatment duration. |
| `RoadReport` | A Citizen, Police or Sensor report plus the road's known local weather. |
| `TrafficObservation` | A reading at one position in a directed road's historical sequence. |
| `Scenario` | All checked inputs, probability tables and warnings. |

`Road.key` gives `(source, target)` so evidence joins the right direction. `Road.id` creates a readable edge name because the files give no separate road ID. `Road.normal_seconds` divides metres by metres per second.

`Responder.initial_ready_at` describes the start of the run. The simulator keeps later availability separately. `Scenario.known_incidents(now)` filters by release time. Assignment and completion status live in the simulator.

## Input checks in loaders.py

The file readers check syntax. The scenario loader checks what the values mean. This keeps IDs, labels and capabilities as text while numbers are parsed where expected.

| Internal helper | What it checks |
| --- | --- |
| `_unique_object`, `_invalid_constant` | Duplicate JSON keys and invalid constants such as NaN and Infinity. |
| `_fields` | Required object keys. |
| `_text` | Nonempty text, without silently trimming IDs. |
| `_number` | Numeric conversion, fractions, finite values and ranges. |
| `_choice` | Whether a label or reference is allowed. |
| `_unique` | Duplicate IDs before one record can overwrite another. |
| `_distribution`, `_matrix` | Probability labels, ranges and row sums. Inputs are not repaired. |

The seven loading steps are nodes, roads, responders, incidents, road reports, traffic history and model tables. Loading the map first lets the later steps check locations. Broken input stops the run. Missing evidence and impossible situations, such as a deadline before release, produce warnings.

Traffic readings are grouped by direction and sorted by `observation_nr`. That number is their order, with no effect on incident release time. Report tables use `table[true_status][reported_status]`. HMM tables use `transition[current][next]` and `emission[hidden][observed]`. The loader checks the tables. The Bayesian and HMM modules then use them for separate calculations.

## Graphs and the different road rules

`graph.py` maps each node to its outgoing edges. An edge has a destination, road ID and fixed duration. Reverse edges must be added explicitly. `neighbors` gives a tuple to protect the internal list from accidental edits.

`routing.build_graph` builds a fresh graph from the scenario. With no status mapping, it uses normal time for every road. With a complete explicit mapping, Open uses normal time, Congested uses 1.5 times normal, and Blocked is left out. It requires a complete mapping so missing entries are caught. The scenario stays untouched. The explicit-label version is useful for tests and the baseline.

`bayesian.infer_road_status(probabilities, weather=..., reports=...)` multiplies the prior and likelihoods and normalizes across all three states. It sums over unknown weather and gives missing reports a factor of one. `infer_scenario` repeats this by directed road, including roads with no reports. It returns probabilities.

`risk_routing.build_bayesian_graph(scenario, beliefs, blocked_threshold=...)` makes the road-use decision. It excludes probabilities at or above the supplied cutoff and gives each allowed edge an average traversal time assuming it is passable. It keeps the full distributions rather than picking one road label. `route_blockage_bounds` gives a separate lower and upper bound without assuming road failures are independent.

The Bayesian CLI example in the README prints beliefs, policy, route, travel seconds and risk bounds. A missing route is `null`. A route can have a blockage bound above the cutoff because the cutoff checks one edge at a time. UCS minimizes estimated seconds. Bayesian and HMM tests cover probability arithmetic, unknown weather, road policies, all-pairs routes and CLI behaviour. [Formulas and examples](DESIGN.md)

## Uniform-cost search in search.py

UCS explores the next path with the smallest accumulated cost `g(n)`.

| Name | Job |
| --- | --- |
| `frontier` | Heap of `(cost, tie_counter, node)` entries to explore. |
| `serial` | Counter that breaks equal-cost ties in discovery order. |
| `best` | Cheapest discovered cost to each reached node. |
| `parent` | Previous node and chosen road, used to rebuild the route. |
| `candidate` | Cost of reaching a neighbour through the current node. |

When a cheaper route appears, push a new heap entry. The old one is skipped when popped if it no longer matches `best`. This avoids editing priorities inside the heap. Accept the goal when its current best entry is popped, since a newly discovered route to the goal could still be improved. Walk backwards through `parent`, then reverse the result. Adding only strictly cheaper candidates stops equal-cost zero-time loops.

`Route.seconds` is travel time. The simulator adds departure to get arrival, then subtracts release to get response time. If the heap empties, return `None`. Start equals goal returns one node, no roads and zero travel. The shortest-path guarantee applies to the fixed, finite graph with nonnegative costs, within the time estimates used.

## Historical traffic in hmm.py and traffic_routing.py

`hmm.forward_filter(tables, observations)` starts from the supplied initial probabilities, applies the first observation, then predicts and updates for each later reading. It returns all three traffic-state probabilities. `infer_traffic(scenario)` checks and sorts each directed history, runs Forward once and returns `TrafficBelief` records with `observation_count` and `prior_only`. A road with no readings keeps the supplied prior. This code works with historical sequences independently of route duration, dispatch and the simulation clock.

`TrafficRouter` stores `normal_seconds * P(High)` by directed road ID. `exposure(route)` adds these scores. `_shortest` uses a UCS queue ordered by (travel, exposure). `_bounded` keeps useful alternatives at each node, including a faster route with more exposure and a slower one with less, as long as they fit the time limit. The router checks the extra time and minimum exposure reduction against the fastest reference route. `describe` reports the chosen and reference times and scores, extra seconds and relative improvement. The search raises an error if its label limit is exceeded.

When `simulate` receives no custom planner it uses plain UCS. With a traffic planner, it gives it the graph, current endpoints and remaining arrival time in strict mode. `_check_route` checks the shape, edges and summed travel seconds. The route's Bayesian seconds drive arrival, completion and CP-SAT response cost. Exposure only helps select a route. Strict mode prevents a detour that arrives late. Late mode can select one and records its deadline outcome.

The explicit CLI accepts `--traffic-policy hmm-tie` or `hmm-bounded` with Bayesian routing. Bounded mode needs `--max-extra-fraction`. Its minimum exposure reduction defaults to .10. The explicit CLI default `bayesian-only` uses plain UCS. JSON keeps traffic beliefs and their history information, exposure, travel seconds and road blockage bounds separate. `benchmark_traffic.py` compares all three policies with both allocators and deadline modes and checks all endpoint pairs. [Saved traffic comparison](results/traffic_comparison.json)

## Simulation in simulation.py

`simulate(scenario, graph, dispatcher, strict_deadlines=True, decision_times=())` makes a private graph copy and keeps the changing state separate from the original inputs. The event heap jumps to releases, initial readiness, arrivals and completions. Events at the same time are applied before dispatch. Zero-duration chains finish before final deadline checks. A deadline already met cannot end ongoing treatment or extend the run.

`simulation_models.py` defines frozen decision views, requests, candidates and results. The dispatcher receives a `DecisionSnapshot` with the time, revealed calls, responder states, current candidates and deadline policy. It returns `AssignmentRequest` IDs. The engine checks the full batch before committing routes and times. The interface allows dispatch only for revealed work and available responders. Committed assignments stay fixed.

A responder's location is `None` while travelling. On arrival it becomes the incident node and treatment starts. They become free there at completion. Initially busy units become free at their supplied start node without a made-up previous incident. Work status is pending, travelling, treating, completed or closed unassigned. Deadline status is separately not due, met or missed. Strict mode closes pending calls after their deadline. Late mode can finish them with a missed deadline, and closes remaining unhandled work when no events remain.

`scripted.py` reads JSON fixtures and uses each timestamp once. Pass its `decision_times` for extra wake-ups. Script writers can know the input in advance, while the engine still checks that calls have been released. Scripts test execution. CP-SAT makes the automatic decisions.

The result contains commitments in time order and event logs. The run uses deterministic estimates. CLI risk bounds do not simulate road failures. Function and view docstrings explain parameters and what callers can expect before and after the call.

## Allocation in allocation.py

`CspDispatcher(snapshot)` builds a new Boolean model from current candidates. `x[r,i]` chooses a responder and call. `y[i] = sum_r x[r,i]` is also Boolean, so a call can get at most one responder. Each responder sum is at most one. Ineligible pairs have no variable. Leaving calls unassigned is feasible, but coverage is considered before minimizing time.

The solver maximizes Critical, High, Medium and Low counts in order. In late mode it then maximizes on-time counts in that order. Finally it minimizes total response, rounded up to integer milliseconds in the objective. There is no extra urgency, deadline ranking or waiting-age bonus. Only a proven optimum is fixed for later stages. Simulation times stay unrounded. Diagnostics record stage statuses, bounds and elapsed time, and distinguish proven optima from feasible results and exhausted budgets. The allocator never receives future input.

`NearestDispatcher` uses the same candidates and sorts by travel then stable IDs. It takes pairs while both members are free in that batch. This is a simple comparison, with no guarantee of the best matching. `statistics.summarize` counts completed work and on-time arrivals, calculates percentages over all and handled calls, and averages response among completed calls. Empty denominators give `None`.

The CLI supports CSP, nearest, scripts, route inspection and comparisons. `benchmark.py` runs the controlled comparison. In Scenario 3, an equal-cost first assignment changes where qualified responders are for later calls, so the best current CP-SAT decision does not guarantee the best full run. [Saved allocation comparison](results/allocation_comparison.json) · [Test results](TESTING.md)

## Export and replay

`outputs.make_plan(result)` copies each `AssignmentRecord` into the required responder ID, incident ID, node path and departure time fields. `write_outputs` validates the plan and checks independently replayed travel, arrival, completion and statistics against the run. Then it saves `plan.json` and `statistics.txt`. The exporter uses the existing assignments. `render_statistics` adds units, definitions, priority counts, unhandled IDs, validation and settings. Empty measures show N/A.

`plan_validation.load_plan(path)` rejects malformed JSON, duplicate keys and NaN/Infinity. `validate_plan(original_scenario, decoded_plan, ...)` checks the exact shape, IDs, skill, release, readiness and previous completion, current location, directed roads, Bayesian edge cutoff and time, and deadlines. It sorts by start time, keeping original row order for zero-duration jobs at the same time. It calculates travel and treatment from the inputs. It shares Bayesian inference and a statistics dataclass, while independently rebuilding the replay without the simulator, graph builder, search or `summarize`. Errors identify the row and rule.

`PlanValidation.valid` means the plan follows the chosen policy. `deadline_compliant` also requires every assigned arrival on time. Coverage comes from unhandled IDs and metrics. Invalid plans have `statistics=None`. The standalone validator does not need OR-Tools. It exits 0 for a valid plan, 1 for an invalid plan and 2 for file or configuration errors.

Menu runs save in a scenario folder. Explicit normal and script runs use the current directory or `--output-dir`. Comparisons create `csp` and `nearest` subfolders. Route inspection writes no plan. Explicit runs print JSON with output paths and validation. [Run commands](README.md)

## Tests

`tests/test_foundation.py` uses small graphs you can check by hand. `tests/test_scenarios.py` checks real inputs, road-status effects and 845 ordered node pairs against Bellman–Ford, a separate shortest-path method. It also breaks temporary copies of inputs to test errors and warnings.

```console
python -m unittest discover -s tests -v
```

[Full testing notes](TESTING.md)
