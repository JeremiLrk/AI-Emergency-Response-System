# How the system makes decisions

The program plans emergency responses on a city map after a storm. It loads and checks the scenario files, estimates road conditions, finds routes, assigns responders, and simulates travel and treatment. It then writes the assignment files and checks them by replaying the plan from the original data.

The design uses the assignment PDF (pages 1–6), the course slides on search, CSP, Bayesian networks and HMMs, and all seven files in each of the three scenarios. [Scenarios/README.md](Scenarios/README.md) explains the units and timing. [DATA_SCHEMA.md](DATA_SCHEMA.md) lists the exact input fields and counts.

## From input to dispatch

1. `load_scenario` reads the files into a `Scenario`. The input records are frozen dataclasses. Their nested probability and history dictionaries should also be treated as read-only.
2. `infer_scenario` calculates three road-condition probabilities per directed road. `build_bayesian_graph` filters roads and gives the usable roads estimated travel times. The all-open graph is available as a comparison.
3. `infer_traffic` processes each road's historical traffic readings. A traffic-aware route planner can use those results as a separate preference when searching.
4. The simulator releases incidents at their timestamps. It builds possible assignments for the currently available responders. The allocator receives only the current decision, then returns responder and incident IDs.
5. The simulator carries out the assignments. The exporter writes the plan and statistics after independent validation.

Search works with a fixed graph. It does not need incident or responder data. The loader can read the entire incident file, but the dispatcher receives neither the full scenario nor the future event queue. `Scenario.known_incidents(now)` is also available as a standalone way to see which incidents have been released.

## Time, deadlines and responder availability

- Distances are in metres, speeds in metres per second, and all times in seconds. Normal travel time is distance divided by speed, with no conversion factor such as 3.6 or 3600. Routing and simulation preserve fractional seconds. CP-SAT rounds up only the response-time objective coefficients. A future integer clock would need to document its precision and could round travel up and deadlines down, which might exclude borderline assignments.
- A deadline is the latest permitted **arrival time** in the strict plan. An incident released at 10 with deadline 50 can be reached at 50, and treatment can finish later. Completion is departure + travel + treatment. Response time is arrival − release, so it includes time spent waiting for dispatch.
- Available responders are ready at time zero. A Busy responder is ready after `time_until_available`. They become free at the supplied start node because the files give no other destination for their initial job. Busy with zero remaining time is allowed. Available with positive remaining time is inconsistent and rejected.
- A responder is occupied from departure until completion. A job cannot be interrupted once assigned. If one job ends at time \(t\), the next can start at \(t\). The responder stays at the incident node, and the system makes no reservations for future calls.
- Strict mode rejects estimated late arrivals and closes waiting calls after their deadline. The experimental allow-late mode can finish a call that missed its deadline. Work status and deadline status are separate. A deadline before release is valid input but cannot be met in strict mode. Late mode can still respond. The loader warns if no responder has the required skill.

## Bayesian road estimates

Roads are directed. Evidence for A → B belongs to that direction only. Reports and local weather are available at time zero. The loader rejects duplicate directed roads, invalid references, repeated report sources for a road, and conflicting weather for the same road.

`bayesian.py` uses the model **Weather → Road condition → Reports from citizen, police and sensor**. The three road conditions are Open, Congested and Blocked. For each condition, multiply its weather-based probability by the likelihood of each available report. Divide each weight by the sum of all weights. The likelihood tables are indexed as `table[true_status][reported_status]`.

When weather is unknown, add the contribution from every weather state:

```text
P(status) = sum over w of P(w) * P(status | w)
```

A missing report contributes a factor of one because the possible report outcomes sum to one. This assumes that missingness itself tells us nothing about the road. A road with neither reports nor known weather uses `(.685, .180, .135)` for Open, Congested and Blocked. The model does not borrow the weather or reports of neighbouring or reverse roads.

All three scenarios have the same Bayesian tables. The calculation uses exact sums and products for this small network, without sampling or a general Bayesian library. See Bayes' Nets part 1 slides 10–17 for factorization and conditional independence, and part 2 slides 4–6 and 11 for evidence, normalization, enumeration and elimination.

The calculation assumes the sources are independent once the road condition is known. If sources copy each other, the result can be too confident. Direct multiplication works for up to three sources. Evidence with zero likelihood, including extreme numerical underflow, raises an error. Reports are applied once. Road status is treated as fixed because there is no data about its changes over time. The system keeps all three probabilities for every road and leaves the input tables alone. It estimates individual roads without inferring their true states or a joint model of several roads.

**Worked example from Scenario 1.** On N1 → N2, the weather is Rain. Citizen and Police report Blocked, and Sensor reports Congested. The weights are `(.00012, .00384, .00441)`. Dividing by `.00837` gives `(.014336917563, .458781362007, .526881720430)`. The reverse road has three Congested reports and gives `(.005911718339, .993168681030, .000919600631)`.

### Decide which roads to use

An earlier idea was to select the most likely state for each road, called MAP. The user chose to keep the full probabilities. `risk_routing.py` handles the separate planning decision. It accepts only roads with `P(Blocked) < threshold`. The threshold must be in [0, 1]. Equality excludes the road. Zero removes all roads, and one removes roads that are certainly blocked. The Bayesian API and explicit CLI require a threshold. The menu supplies .20 for every call, and .20 is also the comparison setting. The assignment provides no calibrated cutoff. Probabilities are kept even for excluded roads.

The estimated duration of an allowed edge is:

```text
normal_seconds * (P(Open) + 1.5 * P(Congested)) / (P(Open) + P(Congested))
```

This is the average edge time **assuming that edge is passable**. The sum is the seconds used by the planner. If roads are dependent, the sum can differ from the expected time given that the entire route is passable. There is no supplied time for traversing a blocked road. An earlier idea of adding a blockage penalty to time could even make a risky edge appear faster if the penalty were too small. It would need its own decision model and is unsuitable for deadline checks.

`build_graph` provides the all-open graph or uses a complete mapping of explicit road labels. Bayesian routing uses `build_bayesian_graph`. The original UCS algorithm works with either graph and minimizes estimated time. A safer but slower route can lose.

For the distinct directed roads used by a route, with individual blockage probabilities \(p_i\), the reported bounds are:

```text
max(p_i) <= P(at least one road is blocked) <= min(1, sum(p_i))
```

These bounds require no assumption of independence between roads. A repeated edge counts once because its state is fixed. A route with no edges has bounds (0, 0). The bounds do not measure lateness or prediction accuracy. The route can have more risk than the edge cutoff even if every edge passes it. A rule that limits total route risk, a model of how roads fail together, and simulation of what happens when a responder reaches a blockage are possible extensions.

At .20, Scenario 1 routes N1 → H1 → N2 in 86.7780346821 seconds with bounds [.135, .27]. The direct road takes 51.6666666667 seconds at normal speed but has blockage probability .5268817204. At .10 the requested route disappears. In Scenario 2, .20 removes N1 ↔ N2, with blockage probability .8301957831 in each direction, leaving 60 of 132 ordered pairs of distinct nodes reachable. The program keeps the chosen threshold when a destination is unreachable. [Testing details](TESTING.md)

## Historical traffic and the HMM

The earlier chat mixed two ideas. **Road condition** is Open, Congested or Blocked. **Traffic level** is Low, Medium or High. In the HMM, both the hidden level and the noisy observation use those three traffic labels. An observation of High is evidence about the hidden state, which can still be Low or Medium.

The file contains history known before the run. `observation_nr` gives the order for each direction and does not specify simulation seconds. The files give neither the age of the data nor the time between readings. We process the history once at startup and keep the final probabilities for the run. This makes them a historical stand-in for current traffic. We do not add live observation events, guess a transition per second, add a prediction over the unknown time gap, or replace missing history with a long-run average. Roads with no readings use that scenario's initial probabilities.

The user rejected proposals that multiplied the road time by an HMM factor or used the maximum of two factors. Those could give an Open road more than its normal duration and count congestion twice. Bayesian road conditions determine time. The HMM gives a separate route preference. We do not multiply probabilities about these different states, use the same report as evidence for both, or assume a joint probability model or independence between the two concepts.

### Forward filtering, step by step

Use the initial distribution as \(P(X_1=x)\), the state for the first observation. Multiply it by the chance of that first reading and normalize. For each later reading, predict the new state from **all** previous states, then multiply by the chance of the reading and normalize again.

```text
T[y][x] = probability of moving from state y to state x
E[x][e] = probability of reading e when the hidden state is x
w1(x) = initial(x) * E[x][e1]
b1(x) = w1(x) / sum_z w1(z)

prediction_k(x) = sum_y b_(k-1)(y) * T[y][x]
w_k(x) = prediction_k(x) * E[x][e_k]
b_k(x) = w_k(x) / sum_z w_k(z)
```

This is Forward filtering from HMM slides 3–4, 9 and 17–23. Viterbi (slides 31–34) finds a single most likely hidden sequence, while Forward adds up contributions from many sequences. Normalizing at each step helps avoid tiny numerical products. Impossible observations raise an error. The supplied positive tables avoid that issue. The course's umbrella example also illustrates starting at \(X_0\). This implementation uses the \(X_1/E_1\) starting point above, so there is no transition before the first observation.

Scenario 2 starts at (.50, .35, .15), while Scenarios 1 and 3 start at (.60, .30, .10). Scenario 2 uses these rows in Low, Medium, High order:

| State | Next-state probabilities | Reading probabilities |
| --- | --- | --- |
| Low | .75, .22, .03 | .80, .18, .02 |
| Medium | .15, .70, .15 | .15, .70, .15 |
| High | .03, .22, .75 | .02, .18, .80 |

For H2 → N8 the readings are Low, Medium, High, Medium, High. The first weights (.4000, .0525, .0030) sum to .4555. The second prediction is (.676103183315, .275323819978, .048572996707). Applying the second reading gives weights (.121698572997, .192726673985, .008743139407), with sum .323168386389.

| Readings processed | P(Low) | P(Medium) | P(High) |
| ---: | ---: | ---: | ---: |
| 1 | .878155872667 | .115257958288 | .006586169045 |
| 2 | .376579449360 | .596366111606 | .027054439034 |
| 3 | .041359105118 | .421348676462 | .537292218420 |
| 4 | .049706783670 | .739730632892 | .210562583438 |
| 5 | .010113305926 | .282220273412 | .707666420662 |

N8 → H2 has no readings and uses (.50, .35, .15). The program retains all three probabilities, the observation count and whether it used only the starting distribution. The scenarios have readings for 14/14, 3/30 and 10/60 directed roads, with 140, 15 and 100 readings respectively. Having only a prior means the traffic level is uncertain.

### Choose a route using traffic as a preference

The traffic score \(Q\) adds `normal_seconds * P(High | history)` for each edge traversal. Longer edges contribute more for the same probability. A repeated traversal contributes again. The score needs no independence assumption and uses High only, although the full distribution is available. It measures historical exposure for comparing routes. Travel time, road blockage probability and route safety are separate.

| Policy | What it does |
| --- | --- |
| `bayesian-only` | Use original UCS to minimize Bayesian seconds. |
| `hmm-tie` | Minimize time first and exposure second. Time ties use exact equality, without rounding or a tolerance. The queue stores both values. |
| `hmm-bounded` | First find the fastest route with the lowest exposure among ties, with time T* and score Q*. Search for the lowest score, then shortest time, within (1 + allowance) × T*. Accept it only when Q < Q* and Q ≤ (1 − minimum reduction) × Q*. Otherwise use the reference route. |

Zero time or zero reference exposure does not lead to a detour. Zero allowance gives the exact tie policy. Both fractions must be finite and in [0, 1]. The CLI requires the allowance in bounded mode. We chose 5% extra travel and 10% minimum exposure reduction before seeing the results. All scenarios, responders and deadline policies use those settings in the comparison. Other settings are useful for separate, planned sensitivity tests.

At a junction, a faster route may have higher exposure than a slower route. Bounded search keeps both choices when useful. A label (time, score) can be removed if another gets to the same node with no more time **and** no more exposure. The queue explores by (score, time). Nonnegative costs and this comparison prevent redundant cycles. This is a project extension to UCS. The number of labels can grow exponentially, so the configurable 100,000-label limit raises `TrafficSearchLimit` if exceeded.

The simulator passes the graph, endpoints and remaining arrival budget to the planner. Strict mode caps detours at that budget and still checks the actual sum of departure and travel against the deadline. A shortest-route fallback handles a subtraction boundary affected by floating-point rounding. The simulator checks the path shape, directed edges and exact sum of the original graph seconds. `Route.seconds` gives the selected travel duration. It determines arrival, treatment completion and availability, and feeds the CP-SAT response time. The exposure score stays separate.

Allow-late mode has no hard route deadline cap. A detour can make an otherwise on-time pairing late. CP-SAT gets the resulting `on_time` flag and one route per pairing. Route choice and allocation are separate, and committed routes stay fixed. Lower exposure can come with a higher Bayesian blockage bound, even while every edge passes the cutoff.

Exact time ties changed no routes in these scenarios. Bounded routing changed seven endpoint pairs in Scenario 3 and no actual dispatch commitments. [Test results](TESTING.md) · [Traffic comparison](results/traffic_comparison.json)

## How uniform-cost search works

`search.py` follows search slides 44–47. A heap gives the next path with the lowest total cost so far. A map remembers the best cost per node, and parent pointers record how to rebuild the route. Skip old queue entries when a better path has replaced them. Accept the goal when it is removed from the queue. Only queue strictly better costs, which also prevents equal-cost zero-time cycles from repeating.

`Route` holds node IDs, road IDs and total travel seconds. Starting at the goal gives one node and zero travel. Unreachable goals return `None`. For a finite fixed graph with finite, nonnegative costs and representable sums, UCS finds a minimum-cost route for the model. The course's positive minimum edge-cost assumption for infinite search trees is stronger than needed here. If costs change, start a new search on a new graph.

The current search does not need coordinates. In the supplied scenarios, distances are at least the straight-line distance, so a later A* version could use straight-line distance divided by maximum speed as a lower bound when modeled costs only increase. UCS remains the reference for these small graphs.

## How the event simulator works

`simulation_models.py` defines frozen views and results. `simulation.py:simulate` owns a private graph copy, event queue and changing state. `allocation.py` and `baseline.py` provide automatic callbacks. `scripted.py` provides fixed requests for testing. Scripts can be written with knowledge of later calls, so a successful script checks execution rather than online decision quality. The interface guards against accidentally exposing future input to the allocator. Arbitrary Python callbacks can still read files on their own.

`simulate(scenario, graph, dispatcher, strict_deadlines=True, decision_times=())` calls the dispatcher with a snapshot of the time, revealed incidents, responders, eligible routes and deadline rule. The dispatcher returns `AssignmentRequest` IDs. The engine checks the whole batch before committing anything, including current availability, release, capability, route, deadline, and repeated responders or incidents. Invalid scripts raise an error rather than partly committing. Earlier events remain processed if a callback fails, and the run returns no successful result. Future reservations and multi-job scheduling are outside the current model.

The event heap orders events by (time, insertion counter). It processes all releases, initial readiness, arrivals and completions at a timestamp before asking for a decision. Dispatch records the route, departure, arrival and completion. A responder is `initially_busy`, `available`, `travelling` or `treating`. Location is `None` during travel. Arrival sets the location and starts treatment, and completion frees the responder there. An initial Busy job has no invented route or incident, and zero remaining time is processed before the first time-zero dispatch.

Incidents move through `pending`, `travelling`, `treating`, `completed` or `closed_unassigned`. Their deadline status is separately `not_due`, `met` or `missed`. Before finalizing deadline misses, the engine processes same-time zero-travel arrivals and zero-treatment completions. It can ask for another decision at the same timestamp after those changes. Each incident can be assigned once, so the process ends for a finite stream. An empty decision advances the clock. If an incident's deadline is before its release, the deadline is already missed at release, without an event in the past.

Strict mode closes missed pending work with `strict_deadline_unassigned`. Late mode can dispatch after the deadline and record both completed and missed. When no events or wake-ups remain, waiting calls close with `no_more_events_unassigned`. No route or qualified free responder means there is no candidate at that moment. Later availability can change that.

The engine still processes future releases when the current dispatch is empty and finishes every committed job. Deadlines already met do not extend the run. The final time is the last relevant event, including initial availability and explicit wake-ups even when otherwise idle. Scripts use wake-ups for delayed departures. Each script timestamp is consumed once, including during zero-duration chains.

The clock keeps exact float comparisons rather than merging nearby times. Display rounding never feeds the clock, although float boundaries can still affect a decision. Overflow and positive durations too small to advance a huge float clock raise `ValueError`. A conservative integer clock is a possible alternative. Simulation uses the frozen travel estimates as durations. It does not simulate actual blockages, recovery, or forecast accuracy. CLI blockage bounds describe uncertainty without creating failure events.

The Scenario 1 script uses the .20 Bayesian cutoff:

| Responder / call | Departure | Arrival | Completion |
| --- | ---: | ---: | ---: |
| R1 / I2 | 0 | 86.778035 | 116.778035 |
| R2 / I4 | 0 | 53.067823 | 63.067823 |
| R4 / I1 | 10 | 66.968786 | 76.968786 |
| R1 / I5 | 120 | 197.347140 | 217.347140 |

All four finish and meet their arrival deadlines. I5 has deadline 200, so treatment can end at 217.347140. I3, I6 and I7 are left unassigned and miss their deadlines because the fixture does not request them. At 116.778 R1 is free at N2. The script waits until 120 to dispatch I5, which was released at 50. [Independent replay](TESTING.md)

## How CP-SAT chooses assignments

The user accepted Boolean variables and compatibility rules. They declined ranking by earliest deadline, deadline slack, urgency or waiting age before comparing response times. The allocator builds a new model from each `DecisionSnapshot`, with no input files, full scenario or future events. Candidate generation checks release, availability, capability, routing and the deadline policy. The allocator checks the snapshot again, and the simulator checks the selected batch.

For each eligible pairing, Boolean `x[r,i]` says whether responder r takes incident i. Boolean `y[i] = sum_r x[r,i]` limits an incident to one responder. `sum_i x[r,i] <= 1` limits each responder to one assignment. Ineligible pairs have no variable and incidents without candidates have y = 0. Leaving every call unassigned is feasible, so INFEASIBLE signals a model error. This follows CSP slides 2, 9 and 10 on variables, constraints and the CP-SAT Boolean matrix.

Solve each objective in order, fixing a proven optimum before moving on:

1. Maximize the number assigned at each priority, in order Critical, High, Medium, Low.
2. In allow-late mode only, maximize on-time counts in that same order, preserving the earlier counts.
3. Minimize total estimated response time, including waiting since release.

This stops the empty allocation from winning on zero response time alone. A late Critical assignment can rank above on-time High coverage. The model can therefore return a lower overall on-time percentage. Treatment length, keeping scarce skills free and route risk are outside the objective, although each can affect later calls.

Each stage is a linear objective. Skip priority stages that are always zero. Fix an objective by equality only after `OPTIMAL`. Time coefficients are `ceil(1000 * (arrival - release))`, with a safe integer range check. This rounds the objective only. The real-valued deadline checks and simulation clock keep their precision. The integer optimum may differ from a continuous-time optimum. No arbitrary priority weights, large penalties or floating-point hard constraints are needed.

All stages share a configurable two-second wall-clock budget per decision. When calculating time left, include elapsed model building time. Python overhead and model construction cannot be stopped exactly at the limit. The solver uses one worker, seed zero and stable variable and constraint order. Exact ties may differ across versions and platforms. There is no extra rule to resolve them or to reserve skills for future calls.

| Solver outcome | Action |
| --- | --- |
| OPTIMAL | Keep the solution, fix that objective and continue. |
| FEASIBLE | Keep the valid solution and stop, without fixing an unproven optimum. |
| UNKNOWN or time exhausted | Keep the last valid solution, or return no requests if none exists. This can delay work until the next event. The program reports the difference between this and having no candidates, without resetting the budget or switching to greedy. |
| MODEL_INVALID, INFEASIBLE or unexpected status | Raise `AllocationError`. |
| NO_CANDIDATES | Return a trivially optimal empty decision without running the solver. |

Diagnostics show stage status, integer objective values, bounds, solver wall time, number assigned and whether all objectives were proved. Solver runtime does not advance the simulation clock.

## How to read the comparisons

The nearest-responder allocator orders eligible pairs by shortest travel, then responder and incident IDs, and takes each pair if neither has been used. It ignores priority, waiting age and the on-time preference in late mode. It can use up a responder with more skills than the call needs. CP-SAT considers the whole current batch. Both use the same candidate rules, time estimates and road cutoff. This allocation baseline is separate from the all-open **routing** baseline.

`benchmark.py` compares both allocators on all three scenarios under strict and allow-late deadlines, starting fresh each time with cutoff .20. Python 3.12.14 and OR-Tools 9.15.6755 reproduced the saved assignments and metrics. No hidden road states are sampled. [Saved allocation comparison](results/allocation_comparison.json)

In strict Scenario 3, CP-SAT completed 13/20 and nearest completed 15/20 even though each recorded CP-SAT decision was proved optimal. For the initial First aid call I4, R1 and R2 cost the same. CP-SAT chose R2 and nearest chose R1. R1 can also handle Medical emergency calls and R2 cannot. Their later locations affected I11 and I14. This shows the effect of an earlier tie on future calls. Neither result establishes which allocator is best over the whole scenario. [All measured results](TESTING.md)

## Assignment files and independent validation

The output follows Assignment1 (1).pdf sections 3.1–3.3, 5.1, 5.2 and 8.2 and the scenario README. `plan.json` is a list of four-field records:

```json
[
  {"responder_id": "R1", "incident_id": "I1", "path": ["N1", "H1", "N2"], "time": 0}
]
```

This illustrates the shape, without claiming the assignment is feasible in a specific scenario. `time` is the absolute start of dispatch, with fractional seconds preserved. `path` is the ordered list of nodes, and each adjacent pair identifies one directed edge. A responder already at the incident has a one-node path. A responder can have separate rows for different calls. Unhandled calls have no row. Arrival, duration, traffic score and settings are kept outside this exact schema.

Section 5.2 gives an example text layout and requires the four statistics below, with time units and an explanation of unhandled work.

| Statistic | How it is counted |
| --- | --- |
| Handled | Treatment completed, including permitted late responses. |
| Responders used | Distinct responders with committed assignments. |
| Average response | Arrival minus release, in seconds. Includes waiting and travel, excludes treatment, and averages handled calls only. N/A if none are handled. |
| Deadline percentage | On-time arrivals divided by all calls. Unhandled calls count as missed for this measure. N/A if there are no calls. |

The statistics model also keeps an on-time percentage among handled calls. The text report gives counts by priority, late and unhandled counts, unhandled IDs, a validation result and run settings. It rounds display values while the plan and feasibility checks keep full precision. Read the average alongside coverage because different policies may handle different calls.

`outputs.make_plan` copies IDs, nodes and departure from `SimulationResult.assignments`. `write_outputs` computes `summarize(result)`, runs independent validation, then checks replayed travel, arrival, completion and metrics against the simulation. A mismatch raises before output creation. The exporter uses the original simulation decisions without allocating, searching or scheduling again.

The no-argument menu uses all four AI techniques and writes to `results/menu/ScenarioN/`. Explicit normal, nearest and script runs write in the working directory unless `--output-dir` is supplied. The explicit CLI routing default is the optimistic all-open graph with UCS, and Bayesian and HMM policies can be selected with flags. A repeat run replaces the same files. `--compare` uses separate `csp` and `nearest` folders. `--route` writes neither file and rejects a nondefault output folder. The menu prints the files, while explicit commands print diagnostic JSON with paths and validation. Two file writes are separate operations, and I/O errors propagate.

The required plan schema has no settings. Read the report for the routing policy, threshold and deadline mode, then give the validator those same assumptions. It does not infer a policy from the path or change the cutoff.

### What the validator checks

`plan_validation.validate_plan` takes the original scenario, decoded plan, routing policy and deadline rule. It shares the Bayesian inference and the `Statistics` data container, but rebuilds edge lookup and filtering, travel times, responder timelines and metrics without the graph builder, search, CP-SAT, simulator or its time helper and summary function. It reconstructs timings rather than reading them from a plan.

1. Require the exact list and row fields, known string IDs and nodes, and finite, nonnegative start times. Reject booleans and nonfinite numbers. The JSON reader also rejects duplicate keys.
2. Assign each incident at most once. Allow unhandled calls and allow a responder to take multiple calls over time.
3. Check the responder's explicit capability, release time, initial readiness and previous job completion.
4. Start at the responder's current node, end at the incident, and use existing directed edges in between.
5. Check the Bayesian cutoff on each edge and recompute travel from distance, speed and the conditional formula. Under baseline routing use normal travel time as the model assumption.
6. Check that arrival and completion times are finite and representable. Keep the responder occupied through travel and treatment, then leave them at the incident.
7. In strict mode, require arrival at or before the deadline. Allow-late mode records misses and warnings.

Replay sorts rows by (start time, original row index). Input can be out of order, and row order breaks ties for zero-duration jobs. Finishing at the next departure is legal. Initially busy units start from the supplied node once ready. Invalid plans report row numbers and error codes without giving performance statistics.

`validate_plan.py` is read-only and needs no OR-Tools. It exits 0 for valid under the supplied policy, 1 for an invalid plan, and 2 for a file or configuration error. During export the richer simulation times provide a separate comparison for catching timing errors.

### What a passing check means

A passing plan follows the selected rules and travel estimates. It may still be empty, leave calls unhandled, choose slower routes or have weaker priorities than another valid plan. `deadline_compliant` means the plan passes validation and every **assigned** arrival is on time. Coverage and the deadline percentage over all calls show which work was missed. Late-mode validity uses the relaxed experimental policy. Strict mode is the default for submission examples.

Replay shares the probability model, so it cannot independently prove that model is correct. Actual road conditions and arrival times remain unknown. A plan can show that departures follow releases, while the snapshot tests check whether the allocator had access to future calls. Tests do not prove global optimality, actual safety or calibrated traffic predictions. [Six saved strict and late replays](results/plan_export_validation.json) · [Test cases](TESTING.md)

## What remains

All four AI methods, event execution, exports and standalone validation are implemented. The report, repository submission and access requirements, and oral defence are separate submission work. Actual road failures, recovery and model calibration are limitations of the simulation.

### Proposed improvement for Critical calls

The current planner uses the same .20 menu cutoff for every priority. A future strict-deadline experiment could build normal and higher-cutoff candidates for qualified, free responders. Solve the same batch first with normal candidates, then with the added Critical options. Use fallback only if it demonstrably improves on the proven normal Critical count. If the time limit prevents a clear comparison, keep the normal result.

Compare the entire batch. Two Critical calls can each have a normal route but need the same responder. A different responder using fallback for one could let both be reached. Removing the fallback for each call separately could lose that option.

Keeping Critical first can trade some lower-priority coverage for a Critical gain. Requiring at least the normal High, Medium and Low counts is a separate, more conservative policy. That choice is open. After fixing coverage, minimize fallback use, then compare risk, then response time. The highest edge probability shows the risk of the worst road. It cannot rank whole-route risk by itself, so report bounds and assumptions too.

An estimated on-time arrival assumes a passable route. There is no event for discovering a blockage, recovering or rerouting. Independent replay would check qualification, availability, deadline and the cutoff for each route. To confirm that fallback improved Critical coverage, rebuild the decision and check the normal-only optimum. Keep that audit evidence separate from the required four plan fields.
