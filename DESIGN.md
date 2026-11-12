# Why the system works this way

This document explains the rules we chose and what they mean. [CODE_GUIDE.md](CODE_GUIDE.md) shows where those rules are implemented. [TESTING.md](TESTING.md) explains how we checked them and what happened on the three scenarios.

## The normal run in one minute

| Question | Current answer |
| --- | --- |
| Which roads can be used? | Roads with less than 20% estimated blockage probability. |
| What determines travel time? | Bayesian Open/Congested probabilities, assuming the road is passable. |
| What does the HMM change? | Route preference; it never adds another slowdown to travel time. |
| Who gets help first? | Critical, then High, Medium and Low, before minimizing response time. |
| Can responders arrive late? | Not in the default run. The separate allow-late option permits it. |
| What happens after treatment? | The responder becomes free at that incident location. |
| Does the planner know future calls? | No. It sees calls only after release. |
| Are arrivals guaranteed? | No. The simulation follows estimates and does not execute real road failures. |

The rest of this guide explains those answers. Sections 2–4 cover roads and traffic; 5–6 cover time and assignments; 7–8 cover outputs and explanations. Section 10 lists ideas that are still proposals.

## The main idea

The program has four separate jobs:

1. Bayesian reasoning estimates whether each road is Open, Congested or Blocked.
2. The HMM estimates historical Low, Medium and High traffic probabilities.
3. Search finds routes using the selected road and traffic rules.
4. CP-SAT chooses which currently available responders should take which known calls.

An event-based simulator connects those jobs. It updates time, locations and availability, then asks for another allocation when something changes. It does not give future incidents to the allocator. Input loading can see the whole file; the decision snapshot cannot.

The assignment leaves some planning choices open. The course methods supply the inference, search and constraints; choices such as the 20% cutoff and traffic-detour allowance are ours. They should be explained and tested, not presented as guaranteed safe rules.

## 1. Units, deadlines and availability

Distances and coordinates are metres, speeds are metres per second, and times are seconds. Normal travel time is distance divided by speed. There is no 3.6 or 3600 conversion. Fractional seconds are preserved.

An incident's deadline is an **absolute arrival time**. A call released at 10 with deadline 50 must be reached by time 50, not by 60. Treatment can finish afterwards. Response time is arrival minus release, so waiting before dispatch counts.

A responder is occupied through travel and treatment. A new assignment can start exactly when treatment finishes. The responder stays at the incident afterwards. The current model includes no separate patient transport, hospital handover or return-to-station journey. Dispatched jobs are not interrupted, rerouted or replaced.

An initially Busy responder becomes free after `time_until_available`, at the input start node. That location is an assumption because no other completion location is provided. Busy with zero remaining time is allowed. Available with a positive busy time is rejected.

The default is **strict deadlines**: reject predicted late arrivals and close waiting calls after their deadline. The optional **allow-late** mode can still handle those calls. A completed incident can therefore have a missed deadline. A deadline before release is kept as a warning, not silently changed; strict mode cannot meet it.

## 2. Estimate roads before deciding whether to use them

### What the Bayesian model assumes

The network is Weather → Road condition → Citizen/Police/Sensor reports. Reports are assumed independent once the condition is known. If sources copy each other, the estimate can become too confident.

For each possible road condition:

- start with its probability under the known weather;
- multiply by the likelihood of each report for that condition;
- divide the three final weights by their total.

If weather is unknown, average over the weather states using their supplied prior probabilities. A missing report contributes no evidence; this assumes the fact that it is missing tells us nothing about road condition. With no reports or known weather, the supplied tables give Open/Congested/Blocked probabilities of **(.685, .180, .135)**.

Weather and reports belong to their directed road. A→B does not borrow evidence from B→A or neighbouring roads. Evidence is applied once and treated as fixed. There is no supplied road-state transition model. All scenarios share the same Bayesian tables.

The report tables mean `table[true_status][reported_status]`, not the reverse. Duplicate source reports and conflicting weather are rejected. Zero-likelihood evidence raises an error instead of dividing by zero; direct multiplication is adequate for the three supplied sources but could underflow with a much larger model.

### A calculation we can check

For Scenario 1's N1→N2, weather is Rain. Citizen and Police say Blocked, while Sensor says Congested. The Open/Congested/Blocked weights are **(.00012, .00384, .00441)**. Their sum is .00837. Dividing gives approximately **(.014336917563, .458781362007, .526881720430)**.

The reverse road has three Congested reports and a different result: **(.005911718339, .993168681030, .000919600631)**. Direction matters.

### Our road-use policy

We keep all three probabilities. We rejected treating the most likely condition as certain.

A road is allowed only when `P(Blocked) < cutoff`. Equality excludes it. The cutoff must be between zero and one: zero removes every edge, while one still excludes a certainly blocked road. The menu and comparisons use **.20 for every priority**. Explicit Bayesian commands require a cutoff. The assignment does not provide a calibrated safe value.

For an allowed road, average its Open and Congested times **assuming it is passable**. Open uses normal time; Congested uses 1.5 times normal. In code the factor is `(P(Open) + 1.5*P(Congested)) / (P(Open) + P(Congested))`.

Adding those edge estimates gives the route's travel seconds. It is not a promise of arrival or an unconditional average over blocked-road failures. If road conditions depend on each other, it can also differ from the expected time given that the entire route is passable. We did not invent a traversal time for Blocked roads or add an arbitrary blockage penalty that could make a risky road look faster.

### An edge cutoff is not whole-route safety

For distinct roads with blockage probabilities `p`, route blockage risk is at least the largest `p` and at most their sum, capped at one. These bounds do not require independent road failures. Reusing the same road counts once because its condition is fixed. A route with no edges has bounds (0, 0).

For example, two allowed roads each with risk .15 can together exceed .20 route risk. Lower HMM exposure can also come with higher blockage bounds. The planner is not described as finding the safest route.

In Scenario 1, cutoff .20 routes N1→H1→N2 in 86.7780346821 seconds with bounds [.135, .27]. The direct road has blockage probability .5268817204. At cutoff .10 the route disappears. In Scenario 2, cutoff .20 removes N1↔N2 and leaves 60 of 132 different-node pairs reachable. The program does not silently relax the cutoff to reach more calls.

## 3. What the HMM contributes

### Historical readings, not live traffic events

The HMM states and observation labels are Low, Medium and High traffic. They are different from the Bayesian Open/Congested/Blocked road conditions.

`observation_nr` orders readings for one directed road. It does not tell us simulation seconds, reading age or time between samples. We process the history once before dispatch and keep the final distribution fixed. We do not guess one transition per simulation second or predict across an unknown gap to the present.

Forward filtering starts with the supplied probabilities for the state at the **first** reading. Apply that reading's emission probabilities and normalize. For every later reading, use the transition table to predict the next state, apply the new reading's likelihood and normalize again. Transition rows mean current→next; emission rows mean hidden→observed.

This uses all possible state histories, rather than choosing one sequence as Viterbi does. Normalizing each step avoids very small products over long histories. Impossible observations raise an error. Roads without history keep their scenario's initial distribution, not a guessed long-run average. Scenario 2 starts at (.50, .35, .15); Scenarios 1 and 3 start at (.60, .30, .10).

### Worked traffic example

For H2→N8 in Scenario 2, the readings are Low, Medium, High, Medium, High. The tables, in Low/Medium/High order, are:

| Current hidden state | Next-state probabilities | Reading probabilities |
| --- | --- | --- |
| Low | .75, .22, .03 | .80, .18, .02 |
| Medium | .15, .70, .15 | .15, .70, .15 |
| High | .03, .22, .75 | .02, .18, .80 |

The first weights are (.4000, .0525, .0030), totaling .4555. The next predicted distribution is (.676103183315, .275323819978, .048572996707). Applying the second reading gives weights (.121698572997, .192726673985, .008743139407), totaling .323168386389.

| Readings processed | Low | Medium | High |
| ---: | ---: | ---: | ---: |
| 1 | .878155872667 | .115257958288 | .006586169045 |
| 2 | .376579449360 | .596366111606 | .027054439034 |
| 3 | .041359105118 | .421348676462 | .537292218420 |
| 4 | .049706783670 | .739730632892 | .210562583438 |
| 5 | .010113305926 | .282220273412 | .707666420662 |

N8→H2 has no readings and keeps (.50, .35, .15). The scenarios have histories for 14/14, 3/30 and 10/60 roads, containing 140, 15 and 100 readings. The result keeps the complete distribution, reading count and whether only a prior was used.

### How traffic influences routing

We rejected multiplying Bayesian and HMM slowdown factors, or taking their maximum. That could count congestion twice and change the assignment's Open/Congested travel rules. There is no supplied joint probability model linking the two state systems.

Instead, each road contributes `normal_seconds * P(High)` to a traffic-exposure score. Add contributions for every traversal; repeated traversals count again. This uses no cross-road independence assumption, but it is still a historical preference score, not duration, blockage probability or a safety guarantee. We use High only; the complete distribution remains available.

Three policies are available:

| Policy | Rule |
| --- | --- |
| `bayesian-only` | UCS chooses minimum estimated travel time. |
| `hmm-tie` | Minimum time first; lower exposure only among exact time ties. |
| `hmm-bounded` | Consider limited detours and prefer sufficiently lower exposure. |

For bounded routing, first find the fastest reference route, using lower exposure to break time ties. Then find the lowest exposure within the allowed extra time, breaking exposure ties by travel time. Accept it only if exposure is strictly lower and meets the minimum reduction. Otherwise keep the reference route.

The fixed comparison settings are **5% extra time** and **10% minimum reduction**, chosen before seeing the results. Both fractions must be finite and between zero and one. Zero allowance gives the tie policy. Zero reference time or exposure does not produce a detour.

Keeping alternatives at a junction is necessary: the fastest path to that node may have worse exposure. Discard a path only when another is no worse in both time and exposure. Nonnegative costs prevent useful cycles, but the number of alternatives can still grow very large. Exceeding the 100,000-label limit raises `TrafficSearchLimit` rather than returning an unproved answer.

Strict mode caps selected travel by the remaining arrival budget and checks the absolute arrival again. A UCS fallback handles subtraction rounding near a deadline. In late mode there is no hard cap, so a detour can turn an otherwise on-time candidate late. CP-SAT receives that selected route and its actual on-time flag; it does not jointly choose among several routes for one pair.

The comparison found seven possible route changes in Scenario 3, but no actual dispatch changes. We kept that finding and did not increase parameters afterwards to manufacture an improvement.

## 4. Search methods

UCS orders paths by accumulated travel time. It updates a node only for a strictly cheaper discovery, skips outdated queue entries and accepts a goal on removal. That handles directed roads, parallel roads, zero-cost cycles and unreachable goals. Staying at the goal gives zero travel.

UCS finds a cheapest route for a finite fixed graph with nonnegative representable costs. It does not know the true conditions. If costs change, run a new search. Overflow raises an error instead of making a path appear unreachable.

A* is a separate course-based comparison. It adds a lower bound on remaining time: straight-line distance divided by maximum road speed. The helper checks that roads are not shorter than their geometric distance and graph costs are at least normal road times. The triangle inequality then justifies the bound; congestion and removing edges preserve it. Rounding can cause tiny numerical differences.

A* can reopen a node after a cheaper discovery, so it also handles admissible but inconsistent caller-supplied estimates. Arbitrary callbacks must obey the documented conditions; the implementation cannot prove them automatically. Invalid estimates and overflow are rejected. A* returns actual travel seconds, not its queue priority. Equal-cost routes may differ from UCS. It replaces the earlier outside-course test comparison; the normal planner is unchanged, and no speedup is claimed.

## 5. How the simulator makes a decision

The simulator keeps its own graph copy, event queue and changing state. Simultaneous releases, arrivals, completions and initial readiness are processed before asking for assignments. Events use an insertion counter for stable equal-time ordering.

A `DecisionSnapshot` contains current time, responders, revealed calls, eligible candidates and deadline rule. The dispatcher returns responder/incident IDs. The simulator validates the entire batch before committing any assignment. It never partly commits an invalid batch, though already processed earlier events are not rolled back after a callback error.

A responder is `initially_busy`, `available`, `travelling` or `treating`. During travel the location is `None`; arrival places them at the incident. Incident work status is `pending`, `travelling`, `treating`, `completed` or `closed_unassigned`. Deadline status is separately `not_due`, `met` or `missed`.

Zero-travel arrivals and zero-treatment completions at a deadline are processed before closing waiting calls. Several decisions can occur at exactly one timestamp. Each incident is assigned at most once, so those chains finish. A deadline before release is marked missed on release, without creating an event in the past.

If no assignment is made, time still advances to later events, including future releases. All committed jobs finish. Met deadlines do not keep the simulation running unnecessarily. Final time is the last relevant event, including initial readiness or an explicit scripted wake-up.

Strict waiting calls close with `strict_deadline_unassigned`. Late-mode calls remain available until assigned or no events remain, then close with `no_more_events_unassigned`. No candidate now does not prove none could exist later.

Float times are compared exactly; nearby times are not merged by rounding. Display formatting never changes the clock. Overflow or a positive duration too small to advance a huge clock raises `ValueError`. An integer clock is a possible alternative, but would need an explicit rounding policy. Solver runtime does not advance simulation time.

Scripts can add decision times for delayed departures. Each script timestamp is consumed once, including zero-duration chains. A script may know the scenario in advance; it tests execution, not an online planner's knowledge. The snapshot boundary prevents accidental future exposure, but an arbitrary Python callback could still read external files.

## 6. What CP-SAT optimizes

There is a Boolean choice for each eligible pair: send this responder to this incident or do not. Each responder gets at most one new assignment, and each incident gets at most one responder. Ineligible pairs have no variable. Leaving all calls unassigned is always a valid combination, so unexpected infeasibility indicates a model problem.

The objectives are solved in this order:

1. Maximize Critical assignments, then High, then Medium, then Low, preserving each result.
2. Only in allow-late mode, maximize on-time counts in that same order while preserving coverage.
3. Minimize total predicted response time, including waiting since release.

Coverage comes first because minimizing response alone could reward assigning nobody. There is no separate deadline-rank, deadline-slack, urgency or waiting-age objective. Nor do we optimize treatment length, route risk or keeping rare skills free. A late Critical call can outrank an on-time High call, and that can reduce total on-time coverage.

The model fixes an objective only after `OPTIMAL`. It skips priority levels that are always zero. Response objective coefficients round up to milliseconds with an integer-range check; hard deadline checks and simulation times stay unrounded. An integer objective can break ties differently from full-precision seconds. We do not use guessed priority weights or a large unassigned penalty.

All stages share a two-second wall-clock budget per decision, including elapsed model-building time. Python work cannot be stopped exactly at that limit. The solver uses one worker, seed zero and stable variable/constraint order. Equal-cost tie choices may still differ across versions or machines.

| Outcome | What happens |
| --- | --- |
| `OPTIMAL` | Keep the solution, fix this objective and continue. |
| `FEASIBLE` | Keep the valid solution and stop; do not claim it is best. |
| `UNKNOWN` or exhausted budget | Keep the last valid solution; if none exists, return no assignments and report why. |
| `MODEL_INVALID`, `INFEASIBLE` or unexpected status | Raise `AllocationError`; do not disguise a broken model as impossible calls. |
| `NO_CANDIDATES` | Return an empty decision without invoking the solver. |

Diagnostics retain stage results, bounds, elapsed time and whether every objective was proved. A timeout does not silently trigger a new budget or nearest-responder fallback.

The nearest baseline uses the same eligible pairs but greedily sorts by travel time, then responder/incident IDs. It ignores priority, waiting age and late-mode on-time preference. It can waste a flexible responder. This is different from the all-open routing baseline.

In strict Scenario 3, CSP handles 13/20 and nearest 15/20. At initial call I4, R1/R2 have equal cost. CSP chooses R2 and nearest R1; only R1 also has Medical emergency capability. Later locations affect I11 and I14. A best current decision is not a best whole-scenario plan. We kept the measured result. [Comparison tables](TESTING.md)

## 7. Required files and independent validation

`plan.json` is a list with exactly these four fields per assignment:

```json
[{"responder_id": "R1", "incident_id": "I1", "path": ["N1", "H1", "N2"], "time": 0}]
```

This illustrates the format, not a claim that this row is feasible in a particular scenario. `time` is dispatch start, with fractional seconds. `path` includes both endpoints; a same-location job has one node. Responders can have several rows over time. Unhandled incidents have no row. Settings, arrivals, treatment times and traffic scores stay outside the required schema.

| Statistic | Meaning |
| --- | --- |
| Handled | Treatment finished, including permitted late work. |
| Responders used | Different responders with committed jobs. |
| Average response | Mean arrival minus release for handled calls, including waiting and travel but not treatment. N/A when none are handled. |
| Deadline percentage | On-time arrivals divided by all calls. Unhandled calls do not count as met. N/A for no calls. |

The underlying statistics also keep an on-time percentage among handled calls. The text report adds priority counts, unhandled IDs, late counts, validation, settings and diagnostic explanations. Only display values are rounded. Read mean response together with coverage.

The exporter copies actual simulation commitments. Before writing, it validates the plan and compares independently reconstructed travel, arrival, completion and statistics with the result. A mismatch raises an error. It does not run another allocation or search.

The validator starts with original scenario data and decoded plan rows. It checks exact fields, known IDs/nodes, numeric finite nonnegative starts, valid directed paths, skills, releases, initial/later readiness, travel, treatment, incident uniqueness and deadlines. It rebuilds Bayesian edge filtering and durations without the graph builder, simulator, search, allocator or statistics summary function. It shares Bayesian inference and the statistics record type, which is why separate arithmetic tests remain important.

Rows are replayed by start time, with original order breaking ties. Out-of-order input rows are allowed. Exact completion-time reuse and zero-duration reuse are valid. Invalid plans report row/rule errors instead of performance statistics. The JSON reader rejects repeated keys, NaN/Infinity and malformed input.

`valid` means the plan follows the selected rules. `deadline_compliant` additionally means every assigned arrival is on time. Neither means good coverage: an empty plan can be valid. Late plans must be checked with their relaxed rule. The plan format does not record settings, so the caller must supply the same routing policy, cutoff and deadline rule used to generate it. The validator does not guess them or change them.

`validate_plan.py` needs no OR-Tools. Its exit codes are 0 for valid, 1 for invalid and 2 for file/configuration problems. A final plan cannot establish what future information an allocator saw; snapshot tests check that separately.

## 8. Explanations do not change decisions

Diagnostics copy the checks already made for each pending, revealed call and responder. They record skill, availability, status, location, expected readiness, route existence and estimated arrival when actually checked. Skill is the first failing reason, before availability, but both Boolean results are stored. Busy or unskilled responders have route/arrival marked not checked, not unreachable.

Each decision retains its time, deadline, sequence number, selected batch and existing solver outcome when available. Same-time decisions have different sequence numbers. If an eligible responder went to another call, the explanation names that assignment without guessing its sole cause. A timeout is not labelled proved optimal, and a late candidate is not called on time. Non-CSP dispatchers have no solver status.

Only calls finally closed unassigned receive summaries. These say whether an eligible on-time candidate was ever checked and the earliest arrival actually calculated, including late arrivals, plus responder, check time, closure reason and complete history. No arrival is invented for a busy unit. A strict deadline before release can produce no pending checks at all. The final display snapshot is not counted as a dispatch decision.

`statistics.txt` gives a short per-call explanation with a deadline, best checked arrival and seconds late when relevant. Explicit CLI JSON keeps full history under `simulation.unhandled_explanations`; Python callers use the same result field. `record_diagnostics=False` disables recording for comparisons. No extra route searches, solver calls or events are created.

These explanations describe this run, not every possible allocation. Different earlier assignments, cutoffs or deadline rules could change later availability. Recording takes memory proportional to responder/pending-call checks over decisions. The solver's existing wall-clock limit can still behave differently under different machine loads.

## 9. Normal execution versus explicit commands

The menu uses all four AI methods with strict deadlines, cutoff .20, bounded routing .05/.10 and CP-SAT. It prints and saves `results/menu/ScenarioN/plan.json` and `statistics.txt`.

Explicit commands default to all-open routing unless Bayesian routing is selected. Normal/script runs write in the current directory or `--output-dir`. Comparisons create `csp` and `nearest` subfolders. Route-only inspection writes neither required file and rejects a custom output folder. The menu prints file contents; explicit runs print diagnostic JSON.

Repeated runs replace the same output names. The two output writes are not one atomic filesystem operation, and I/O errors propagate. Graphs and inputs remain unchanged by routing and execution. [Commands](README.md)

## 10. Proposed ideas that are not implemented

**Critical fallback routes.** We discussed raising the road cutoff only when it improves on-time Critical coverage. Normal-only and expanded candidates should be compared across the whole current allocation, because calls can compete for the same normal responder. Use fallback only after a demonstrated gain over the proved normal Critical count; an inconclusive time limit should retain the normal result.

Preserving Critical-first priorities may sacrifice lower-priority coverage. Protecting the normal High/Medium/Low counts is a separate, more conservative policy, not the same objective. That choice remains open. After coverage, the proposal would minimize unnecessary fallback use, compare risk, then response time. The highest edge probability alone cannot rank complete route risk.

The predicted arrival would still assume passability. Independent replay would check the expanded road policy, skills, timing and deadlines; separate evidence would need to rebuild the decision and establish the normal-only optimum. The required plan schema should not change.

**Waiting for a busy responder.** A responder can take another call once free, but there is no reservation for a future second job or deliberate wait strategy. We discussed waiting for a responder already at the same location when that would still meet the second call's deadline. This is not implemented.

**Patient transport and returning to stations.** Currently a responder becomes available as soon as treatment finishes, at the incident location. An ambulance does not then drive a patient to hospital, and no responder automatically returns to a station. A proposed extension would include those extra journeys and, for a hospital trip, any handover time before the ambulance becomes available. It would need clear rules about when a returning unit can accept another call. We would compare returning to a station with staying at the incident or hospital, because that changes the starting point for the next response. These are proposed changes, not current simulation behaviour.

**How we would test these extensions.** For Critical fallback, compare additional on-time Critical coverage with the extra route-risk bounds under declared assumptions; more completed calls alone would not establish a better policy. For actual blockages, test whether discovering a blocked road triggers a valid replacement route and correctly updates arrival and availability. Patient transport and station-return tests would check the extra travel/handover time, busy periods and next departure location. These evaluations have not been run because the extensions are not implemented.

**Actual blockages and live traffic.** There are no events for discovering a blocked road, turning back, rerouting or receiving live readings. No supplied true-state data establishes safety or prediction accuracy. These are limitations, not hidden implemented features.

All four required AI components, simulation, outputs and validation are implemented. The report, repository access, submission and oral defence still need their own final checks.
