# Testing the system

## Yes, we test complete runs

The tests do more than check individual functions. They also load the real scenarios, run the AI pipeline, simulate every assignment, write the output files and check those files against the original input data.

There are **175 tests**. Several tests run many combinations, so that number is not the number of scenarios or individual examples checked.

## Run everything with one command

Open a terminal in the repository folder. Use the environment where you installed the project requirements.

Windows:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

macOS or Linux:

```sh
./.venv/bin/python -m unittest discover -s tests -v
```

With that environment already active, `python -m unittest discover -s tests -v` works too. A successful run ends with `Ran 175 tests` and `OK`. `FAIL` means an expected result did not match; `ERROR` means a test could not finish. Runtime depends on the computer. Replace `-v` with `-q` for less output.

Tests write temporary files and remove them afterwards. The menu test redirects its output folder, so it does not overwrite saved results.

## Which tests exercise the whole system?

### The actual scenario menu

`test_menu_runs_all_scenarios_and_prints_the_saved_files` in `tests/test_outputs.py` runs `run.main()` as if someone chose Scenario 1, 2 and 3 in the console.

It runs the real loader, Bayesian inference, HMM, routing, CP-SAT, simulation, exporter and validator. It checks that both files exist, their contents appear in the console, the settings are correct, and the expected numbers of incidents are handled: **6, 11 and 13**.

The test supplies the menu answer automatically and redirects the output folder. It does not replace the AI calculations with made-up results.

### Eighteen complete scenario combinations

`test_all_three_scenarios_strict_late_and_three_traffic_policies`, also in `test_outputs.py`, checks:

- all three scenarios;
- strict deadlines and late arrivals allowed;
- Bayesian-only, HMM tie-breaking and HMM bounded-detour routing.

That is **18 full simulations and exports**. Each generated plan is read back. Its paths and departure times must match the simulation. Independent validation must reconstruct the same travel, arrival, treatment completion and statistics. The test also checks Critical coverage, unhandled work, late responses and responders taking several jobs over time.

Other tests run the command-line program and standalone validator as separate processes. They check output folders, console JSON, scripts, file names and exit codes. Route-only inspection must not write a plan.

### Checks that diagnoses leave planning unchanged

The diagnostic test runs all three scenarios in strict and late mode with recording switched on and off. Apart from the new explanation field, the complete results must be equal: assignments, times, events, final states, plans and statistics.

During development, we also saved **48 runs before the diagnostic change** and compared them with the changed program. These covered three scenarios, two deadline rules, two allocators and four routing settings. Every original result matched exactly. The same saved comparison was checked after adding A*. This was a before/after check, not a separate planner used to explain calls.

## What the smaller tests check

| File | Tests | Main checks |
| --- | ---: | --- |
| `test_foundation.py` | 6 | Hand-checkable UCS routes, directed and parallel roads, zero-cost cycles, invalid input, readers and travel-sum overflow. |
| `test_scenarios.py` | 12 | Actual file contents, units, skills, availability, release times, damaged inputs and 845 UCS/A* node-pair comparisons. |
| `test_astar.py` | 15 | A* stopping and reopening rules, invalid estimates, overflow, geometry, actual heuristic bounds and independently checked paths. |
| `test_bayesian.py` | 11 | Worked probabilities, missing reports/weather, report order, conflicting evidence, separate road directions and unchanged inputs. |
| `test_risk_routing.py` | 11 | Cutoff boundaries, estimated road times, route-risk bounds, directed routes, CLI options and another 845 UCS/A* comparisons. |
| `test_hmm.py` | 8 | The five-reading example, missing-history priors, direction, normalization, invalid observations and independent hidden-state calculations. |
| `test_traffic_routing.py` | 11 | Equal-time routes, permitted detours, exposure reduction, alternative paths, search limits and the selected route's actual travel duration. |
| `test_simulation.py` | 27 | Releases, simultaneous events, busy units, locations, travel, treatment, zero-duration jobs, deadlines and rejected assignments. |
| `test_scripted.py` | 6 | Script parsing, simultaneous requests, consuming a time once, extra decision times and CLI errors. |
| `test_allocation.py` | 21 | Priority order, responder conflicts, choosing compatible pairs, small exhaustive models, real scenarios and solver limits/statuses. |
| `test_statistics.py` | 9 | Waiting time, late and unhandled calls, empty averages, default execution and allocator comparisons. |
| `test_plan_validation.py` | 14 | Original-data replay, skills, releases, overlapping jobs, directed roads, treatment, deadlines, JSON errors and policy settings. |
| `test_outputs.py` | 12 | Full runs, exact plan fields, departure times, printed/saved files, menu behaviour, comparison folders and validator exits. |
| `test_diagnostics.py` | 12 | Reasons changing over time, competing calls, no responders/routes/skills, late candidates, solver timeout and unchanged planning. |

To run one group, for example HMM tests:

```console
python -m unittest discover -s tests -p test_hmm.py -v
```

### We do not rely only on two algorithms agreeing

The UCS/A* comparisons cover **845 ordered node pairs per graph type**: 25 in Scenario 1, 144 in Scenario 2 and 676 in Scenario 3. They include staying at the same node. Both returned paths are checked, not just their costs. Different equal-cost paths are allowed.

A separate test tries every simple path on 30 small five-node graphs: **750 start/goal cases**. Both UCS and A* must match those independently calculated minimum costs. Other tests check stale queue entries, a costly goal discovered first, and reopening a node after finding a cheaper path. A zero heuristic must behave like UCS. Actual scenario checks verify the straight-line heuristic never overestimates or breaks its edge-by-edge lower-bound rule, allowing only `1e-10` for floating-point rounding in those assertions. Routing itself uses no such tolerance. No A* speed advantage has been measured.

The same idea is used elsewhere: hand-calculated Bayesian results, explicit sums over hidden HMM sequences, all compatible subsets of small CSP models, and exhaustive small detour paths. The HMM tests include all 27 hidden sequences for a three-reading example and normalization over 10,000 readings. Detour tests include 30 small generated acyclic graphs.

Some solver tests deliberately imitate `FEASIBLE`, `UNKNOWN`, exhausted budgets and model errors. This reliably exercises those branches. Other tests use the real solver. We never treat an unproven feasible solution as a proved optimum.

## What we measured on the scenarios

The saved comparisons use blockage cutoff **.20**, solver budget **2 seconds per decision**, one worker, seed zero and integer-millisecond response objectives. The tested setup was Python 3.12.14 with OR-Tools 9.15.6755. Costs and simulation times are still estimates; no hidden road truth is sampled.

### Allocation and deadline results

| Scenario | Deadline rule | Allocator | Handled | On time | Mean response (seconds) |
| --- | --- | --- | ---: | ---: | ---: |
| 1 | Strict | CSP | 6/7 | 6/7 | 91.113 |
| 1 | Strict | Nearest | 5/7 | 5/7 | 82.438 |
| 1 | Allow late | CSP | 7/7 | 5/7 | 102.276 |
| 1 | Allow late | Nearest | 7/7 | 5/7 | 98.938 |
| 2 | Strict | CSP | 11/12 | 11/12 | 33.253 |
| 2 | Strict | Nearest | 11/12 | 11/12 | 33.253 |
| 2 | Allow late | CSP | 12/12 | 10/12 | 32.782 |
| 2 | Allow late | Nearest | 12/12 | 10/12 | 32.782 |
| 3 | Strict | CSP | 13/20 | 13/20 | 607.937 |
| 3 | Strict | Nearest | 15/20 | 15/20 | 586.235 |
| 3 | Allow late | CSP | 20/20 | 11/20 | 1408.182 |
| 3 | Allow late | Nearest | 20/20 | 12/20 | 1378.635 |

CSP handles one more Critical call than nearest in strict Scenario 1. Scenario 2 ties. In strict Scenario 3, nearest handles two more Critical calls. An early equal-cost assignment changes the locations of differently skilled responders for later medical calls. The solver can be optimal for its current decision without producing the best complete run.

Allowing late responses handles every incident in these examples, but can reduce on-time coverage: a late job can occupy a responder needed later. Average response includes waiting and travel for handled calls only, so compare it together with coverage. Different handled subsets make the means an incomplete comparison.

The saved runs proved all relevant CSP objectives or had no candidates. Timeouts did not cause these benchmark outcomes. Different versions or platforms can resolve equal-cost ties differently.

Reproduce the comparisons with an active environment:

```console
python benchmark.py --block-threshold .2
python benchmark_traffic.py --block-threshold .2 --max-extra-fraction .05 --min-exposure-reduction .10
```

Full results are in [allocation_comparison.json](results/allocation_comparison.json) and [traffic_comparison.json](results/traffic_comparison.json). These include assignments, unrounded statistics, settings and solver information.

### Did the HMM change anything?

The traffic comparison runs **36 combinations**: three scenarios, two deadline rules, two allocators and three route policies. The 5% extra-time allowance and 10% minimum exposure reduction were chosen before looking at results.

Both HMM policies produced the same actual assignments, committed routes, departure times and statistics as their matching Bayesian-only run. There were no committed detours and no timeouts explaining that result.

The wider route check did find possible differences:

| Scenario | Reachable pairs, including same-node | Equal-time route changes | Bounded-detour changes |
| --- | ---: | ---: | ---: |
| 1 | 25 | 0 | 0 |
| 2 | 72 | 0 | 0 |
| 3 | 676 | 0 | 7 |

The seven changed directions are N3→H1, H1→N1, H1→N3, H1→N7, H1→N20, H1→P1 and P1→H1. None was dispatched in these runs.

For N3→H1, the shortest route is N3–N4–N9–H1: 1302.620309 seconds and exposure 112.653333. The alternative is N3–N5–N8–H1: 1331.570578 seconds and exposure 62.005453. That is 28.950269 seconds, or about 2.22%, slower for 44.96% less exposure. Its travel duration is **1331.570578**, not its exposure score. Reverse directions can have different scores.

A small timing test makes the distinction explicit: selected travel 21 seconds plus treatment 7 gives arrival 21 and completion 28, not arrival at exposure 2.1. With deadline 20.5, strict mode keeps the 20-second shortest route; late mode can select 21 and records the miss. Invented route durations are rejected.

### How much does the road cutoff remove?

These are graph checks, not incident-handling counts. Same-node pairs are excluded here.

| Scenario | Cutoff | Roads kept | Reachable different-node pairs |
| --- | ---: | ---: | ---: |
| 1 | .10 | 2/14 | 3/20 |
| 1 | .20 | 10/14 | 20/20 |
| 1 | .50 | 10/14 | 20/20 |
| 1 | .90 | 12/14 | 20/20 |
| 2 | .10 | 12/30 | 16/132 |
| 2 | .20 | 28/30 | 60/132 |
| 2 | .50 | 28/30 | 60/132 |
| 2 | .90 | 30/30 | 132/132 |
| 3 | .10 | 12/60 | 20/650 |
| 3 | .20 | 58/60 | 650/650 |
| 3 | .50 | 58/60 | 650/650 |
| 3 | .90 | 60/60 | 650/650 |

In Scenario 2, cutoff .20 removes N1↔N2, whose blockage probability is about .8301957831 in each direction. That disconnects parts of the usable graph. More reachable pairs do not prove that a more permissive cutoff is safer.

## File validation and useful examples

Six strict/late exports are saved under `results/plans/ScenarioN/`. Three normal menu runs are under `results/menu/ScenarioN/`. The six exports' independent checks are recorded in [plan_export_validation.json](results/plan_export_validation.json). All pass under their declared rule. Late plans are valid only under the allow-late rule; they do not satisfy every arrival deadline.

The validator tests include a deliberately empty valid plan, damaged JSON, duplicate incidents, impossible skills/releases, initially busy units, repeated jobs, exact completion-time reuse and zero-duration reuse. They check out-of-order plan rows too. Export refuses fabricated travel, arrival, completion or summary values before writing either output file.

Some hand-checkable examples:

- Travel 5 plus treatment 2 with deadline 5 is on time: arrival is 5, completion is 7.
- Release 1, departure 3, travel 5 gives arrival 8 and response 7. The exported `time` is 3. Treatment 2 finishes at 10.
- Normal road time 5 with beliefs (.2, .6, .2) gives passable-road time 6.875. Equality with the blockage cutoff rejects an edge.
- Scenario 1's all-open H1→N2 route takes 48.0666666667 seconds. This is a route demonstration, not a dispatch result.
- Scenario 1 N1→N2 takes 51.6666666667 all-open seconds. With cutoff .20 it detours via H1 in 86.7780346821 seconds, with blockage bounds [.135, .27]. At cutoff .10 no route is allowed. The direct road's blockage probability is .5268817204.

The scripted Scenario 1 example deliberately handles four calls, not all seven:

| Responder / call | Departure | Arrival | Treatment finished |
| --- | ---: | ---: | ---: |
| R1 / I2 | 0 | 86.778035 | 116.778035 |
| R2 / I4 | 0 | 53.067823 | 63.067823 |
| R4 / I1 | 10 | 66.968786 | 76.968786 |
| R1 / I5 | 120 | 197.347140 | 217.347140 |

R4 starts busy until 10. R1 stays at N2 after I2, then waits until 120 for its scripted next departure. I5 was released at 50 and has deadline 200, so treatment can finish after 200. I3, I6 and I7 are unhandled because this script never requests them. This checks execution; it is not an automatic allocation strategy.

## What passing tests cannot prove

The tests establish behaviour for the checked inputs. They do not prove real-world road safety, calibrated probabilities, or the best possible allocation over every future incident.

The validator independently rebuilds routes and timelines, but shares Bayesian inference and the statistics record type with the application. Separate arithmetic tests check that shared probability calculation. A final plan alone cannot prove the allocator was kept unaware of future calls; snapshot tests check that boundary separately. An arbitrary Python callback could still read files outside that interface.

We have not measured a percentage of code lines or branches tested, so we do not claim 100% coverage. macOS/Linux execution has not been directly tested here. Historical traffic has no supplied age, the simulator has no actual blockage/recovery events, and larger graphs can reach the bounded search's explicit limit. Patient transport, hospital handover, automatic station return and Critical fallback are not implemented or evaluated. Current tests verify availability after treatment at the incident location, not those proposed extra journeys. Tiny differences near floating-point boundaries and solver time limits can matter.

The dependency check is `python -m pip check`. The suite and dependency check passed on the tested setup. A report, repository access and submission still need their own checks; passing tests do not submit the project.

## Earlier test counts

For development history, the suite grew through 17, 39, 72, 102, 121, 145, 148, 160 and finally **175** tests. Statements that a component was unfinished at an earlier stage are not descriptions of the current program. [LLM_NOTES.md](LLM_NOTES.md) keeps the development decisions and corrections.
