# How the code works

This guide follows one normal run. Read [DESIGN.md](DESIGN.md) for why we chose these rules, or [TESTING.md](TESTING.md) for the evidence that they work.

## Start here

Run `python run.py` in the project environment and choose a scenario. The menu uses all four AI techniques. It prints the plan and statistics and saves them in `results/menu/ScenarioN/`.

The main flow is:

```text
Load and check the input files
    ↓
Estimate road conditions with Bayesian reasoning
    ↓
Estimate historical traffic with the HMM
    ↓
Simulate releases, travel and treatment
    ↓
At each decision: find routes → choose assignments with CP-SAT
    ↓
Validate the finished plan → write plan.json and statistics.txt
```

Road and traffic beliefs are calculated before the simulation. Routing and allocation happen again when the current situation changes. Future incidents are kept inside the simulator until their release.

## Where to find each part

| File in `emergency_response/` | Responsibility |
| --- | --- |
| `models.py` | Input records: nodes, roads, responders, incidents and observations. |
| `loaders.py` | Read the seven files and reject inconsistent input. |
| `graph.py`, `routing.py` | Directed graph and normal/explicit-status road costs. |
| `bayesian.py` | Calculate Open, Congested and Blocked probabilities. |
| `risk_routing.py` | Apply the blockage cutoff, estimate travel and report route-risk bounds. |
| `hmm.py` | Process historical traffic with Forward filtering. |
| `search.py` | UCS used by the planner and A* used for comparison. |
| `traffic_routing.py` | Select routes using travel time and a separate traffic preference. |
| `simulation_models.py`, `simulation.py` | Current decision views, event timing, responder state and final results. |
| `allocation.py`, `baseline.py` | CP-SAT allocation and nearest-responder comparison. |
| `scripted.py` | Fixed assignment requests for testing simulation behaviour. |
| `diagnostics.py` | Explain unhandled calls using checks already made. |
| `statistics.py`, `outputs.py` | Count results and export the required files. |
| `plan_validation.py` | Rebuild and check a plan using original inputs. |

The top-level `run.py` connects them. `validate_plan.py` checks a saved plan. `benchmark.py` and `benchmark_traffic.py` reproduce comparisons.

## 1. Read the scenario

`run.main()` handles the menu or command-line options, then calls `load_scenario`.

The loader first checks the map, then responders, incidents, road reports, traffic history and probability tables. It checks IDs, references, labels, numeric ranges, skills and probability rows. It does not silently repair bad data. A missing report is allowed; a road referencing a nonexistent node is not.

Some valid inputs still describe a difficult situation. For example, a call can have a deadline before its release. That produces a warning instead of changing the deadline. Historical readings are sorted by `observation_nr`; duplicate or missing positions within a supplied history are rejected.

The small reader helpers handle repeated JSON keys, NaN/Infinity, missing fields, text, allowed labels, duplicate IDs and probability rows. CSV values stay text until a field needs numeric conversion. CSV column order can vary, but the expected column names must be present.

`Scenario` holds the checked inputs. A frozen dataclass prevents replacing a field, but nested dictionaries can still be edited, so treat all loaded input as read-only.

Useful names:

- `Road.key`: `(source, target)`, used to join evidence to the correct direction.
- `Road.id`: readable edge identity, since the files supply no separate road ID.
- `Road.normal_seconds`: distance divided by speed.
- `Responder.initial_ready_at`: availability at the start, not after later assignments.
- `Scenario.known_incidents(now)`: released incidents only.

For exact CSV/JSON fields, inspect the supplied scenario files and [scenario instructions](Scenarios/README.md). `loaders.py` contains the checks actually enforced by the program.

## 2. Turn road reports into a usable graph

`bayesian.infer_road_status` estimates one road's three probabilities. `infer_scenario` does the same for every directed road. They calculate beliefs; they do not decide whether to drive along a road.

`risk_routing.build_bayesian_graph` makes that decision using `blocked_threshold`. It removes roads whose blockage probability is at or above the cutoff. Allowed roads get an average Open/Congested time assuming they are passable. The full distributions remain available.

`route_blockage_bounds` reports separate lower and upper risk bounds. Those bounds are not travel time, and the edge cutoff is not a bound on a complete route's risk.

The generic `Graph` stores outgoing `Edge` records. Each edge has a road ID, destination and seconds. It never invents reverse roads. `neighbors(node)` returns a tuple so callers cannot edit the internal adjacency list accidentally.

For tests or optimistic comparisons, `routing.build_graph` can instead use all-open times or a complete mapping of Open/Congested/Blocked labels. Missing labels are rejected. All graph builders leave the scenario unchanged.

## 3. Process historical traffic

`hmm.forward_filter(tables, observations)` applies the first reading to the initial distribution, then repeats prediction and observation updates. `infer_traffic` runs it for each direction and returns `TrafficBelief` records.

A belief contains all three traffic probabilities, how many observations were used, and `prior_only`, which says no history was available. Missing histories use their scenario's initial distribution. The HMM does not know dispatch times or create live simulation readings.

`TrafficRouter` uses each road's normal seconds multiplied by its historical probability of High traffic as an exposure contribution. It stores this separately from Bayesian travel time. `exposure(route)` adds the contributions; `describe(...)` reports the selected route and fastest reference route, times, scores, extra seconds and reduction.

Its equal-time policy orders routes by travel time, then exposure. The bounded policy keeps useful alternatives at a node, such as a faster path and a slower path with less exposure. It accepts a detour only within the selected extra-time allowance and minimum reduction. It raises an error if the 100,000-label search limit is reached.

## 4. Find paths with UCS or A*

UCS in `search.ucs` uses these variables:

| Name | Meaning |
| --- | --- |
| `frontier` | Queue of paths still worth exploring, cheapest first. |
| `serial` | Discovery counter to break equal-cost ties. |
| `best` | Cheapest travel cost found so far for each node. |
| `parent` | Previous node and road, used to rebuild the path. |
| `candidate` | Cost of reaching a neighbour through the current node. |

When a cheaper path is found, UCS adds a new entry. The older entry is skipped when removed if its cost is no longer best. It accepts the goal on removal, not first discovery. Only strictly cheaper updates are queued, so equal-cost zero-duration cycles cannot repeat forever.

`Route` contains `nodes`, `roads` and travel `seconds`. An unreachable goal gives `None`; staying at the start gives one node and zero seconds. Invalid endpoints or unrepresentable travel sums raise errors. Costs must stay fixed during search.

`search.astar` uses the course rule `f = g + h`. `straight_line_heuristic(scenario, graph, goal)` builds `h` from straight-line distance and maximum speed after checking the geometry and graph costs. A* can revisit a node after a cheaper discovery. With zero `h`, it behaves like UCS. Arbitrary supplied heuristics must satisfy the documented lower-bound conditions.

A* is used for comparison tests, not selected by the normal menu. The tests compare minimum costs and valid paths, not speed. Actual dispatch still uses UCS or the traffic-aware search.

## 5. Advance the simulation

`simulate(...)` makes a private graph copy and starts an event queue. It jumps to the next release, availability change, arrival, completion or deadline rather than checking every simulated second.

At a decision, it creates a `DecisionSnapshot`: current time, revealed incidents, responder states, eligible candidate pairs and deadline rule. Each candidate already has a route, arrival, completion and on-time flag. The dispatcher receives this view, not the full future scenario.

If no traffic planner is supplied, candidate routes use UCS. A custom planner receives current endpoints and, in strict mode, the remaining deadline budget. `_check_route` verifies its directed edges and travel sum. A shortest-route fallback handles a float subtraction boundary. The selected route's seconds determine arrival and completion; exposure never substitutes for seconds.

The dispatcher returns `AssignmentRequest` IDs. The simulator checks the whole proposed batch before committing any of it. Repeated responders, repeated calls or ineligible pairs cause an error. Earlier processed events are not rolled back after an invalid callback.

During travel the responder's location is `None`. Arrival starts treatment at the incident. Completion frees the responder there. There is no additional patient transport, hospital handover or automatic station return in this model; those are proposed extensions in DESIGN.md. Initially busy units become free at their supplied start node without inventing an earlier job. Incident work status and deadline result are separate. See [DESIGN.md](DESIGN.md) for strict/late and same-time rules.

The result records assignments, final views and processed events. It finishes committed jobs and future releases even after a decision assigns nobody.

## 6. Choose assignments

`allocation.CspDispatcher` builds a new CP-SAT model from the current candidates. A Boolean `x[r,i]` means send responder r to incident i. Responder sums are at most one. Boolean `y[i]`, equal to the sum of incident i's selected pairs, limits that call to one responder. Ineligible pairs have no variable.

The objectives are coverage by priority, optional on-time coverage in late mode, then response time. Only a proved optimum is fixed before the next objective. Costs are rounded up to integer milliseconds for that final objective; simulation and hard deadline checks keep their precision.

The allocator records solver outcomes, bounds and time spent. It distinguishes a proved optimum, a valid solution not proved best, a timeout and a model error. Its wall-clock budget does not advance simulated time.

`baseline.NearestDispatcher` uses the same candidates but greedily takes shortest-travel pairs, then stable IDs. It ignores priority and can consume a flexible responder unnecessarily. It is a comparison, not a guaranteed best allocation.

`scripted.py` lets a test supply requests at fixed times. `decision_times` wakes the simulator for delayed scripted departures. Each timestamp is consumed once. Scripts can be written with knowledge of the scenario; they check execution rather than online planning quality.

## 7. Explain unhandled calls

`diagnostics.py` copies the simulator's actual checks and committed batch. It makes no extra search or allocation attempt. Busy/unskilled responders have route and arrival fields set to `None`, meaning not checked.

`SimulationResult.unhandled_explanations` contains summaries and complete histories for calls left unassigned. The text report gives a shorter version; explicit CLI JSON includes the full records. `record_diagnostics=False` disables recording for comparison tests. These observations cannot prove that every possible earlier allocation would fail.

## 8. Count, check and export the result

`statistics.summarize` counts completed calls, distinct responders and deadline results. It averages arrival minus release for completed calls. An empty average or percentage becomes `None`, displayed as N/A.

`outputs.make_plan` copies assignments into the required four fields. `write_outputs` validates the plan and compares reconstructed timings/statistics with the simulation before writing either file. It does not allocate again. `render_statistics` formats the report with units, priority results, configuration and explanations.

`plan_validation.validate_plan` starts from the original scenario and plan. It reconstructs timelines and road times without calling the simulator, graph builder, search, allocator or summary function. It shares Bayesian inference and the statistics record type, so probability arithmetic still needs its own tests.

A valid plan follows the selected rules; it can still handle few incidents. `deadline_compliant` additionally requires every assigned arrival to be on time. An invalid plan has no performance statistics. The standalone checker needs no OR-Tools and exits 0 for valid, 1 for invalid and 2 for file/configuration errors.

The menu writes scenario folders. Explicit runs use the current folder or `--output-dir`; comparisons create `csp`/`nearest` subfolders. Route inspection writes no assignment files. Explicit commands print JSON, while the menu prints the saved files.

## How to read the comments

**Parameters** explain the arguments and units. **Preconditions** say what must be true before a call; some are checked, others are the caller's responsibility. **Postconditions** describe successful results and state changes. The comments themselves do not enforce rules.

For example, `Graph.add_edge` validates finite nonnegative seconds, but constructing a `Road` record directly does not validate its fields. Normally use `load_scenario` to get checked inputs.

To inspect search alone, run `python run.py Scenarios/Scenario1 --route H1 N2`. This intentionally uses all-open costs, returns about 48.067 travel seconds and performs no dispatch. For complete execution, use the menu or the explicit policies described in the [README](README.md).
