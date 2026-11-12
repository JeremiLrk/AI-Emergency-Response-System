# Testing

## Running the tests

The suite contains **175 tests** and uses Python's built-in `unittest` framework. pytest is not required.

Run from the repository folder with the project environment:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

On macOS or Linux:

```sh
./.venv/bin/python -m unittest discover -s tests -v
```

With the environment already active:

```console
python -m unittest discover -s tests -v
```

A successful run ends with `Ran 175 tests` and `OK`. Replace `-v` with `-q` for a shorter summary. Test outputs are written to temporary folders and removed afterwards.

## Test coverage

| Test file | Tests | Checks |
| --- | ---: | --- |
| `test_foundation.py` | 6 | Basic UCS paths, one-way and parallel roads, zero-cost cycles, invalid costs, file readers and overflow. |
| `test_scenarios.py` | 12 | Scenario fields, units, capabilities, availability, release times, invalid data and UCS/A* comparisons on 845 node pairs. |
| `test_astar.py` | 15 | A* path costs, stopping at the goal, replacing worse paths, reopening nodes, heuristic bounds, invalid inputs and exhaustive small-graph checks. |
| `test_bayesian.py` | 11 | Worked probabilities, missing weather or reports, conflicting reports, separate road directions and unchanged inputs. |
| `test_risk_routing.py` | 11 | Blockage cutoffs, estimated travel times, route-risk bounds, directed roads and UCS/A* comparisons on 845 Bayesian node pairs. |
| `test_hmm.py` | 8 | The Scenario 2 example, Forward calculations, missing histories, initial probabilities, direction, invalid observations and long histories. |
| `test_traffic_routing.py` | 11 | Equal-time routes, bounded detours, traffic-score reduction, search limits and correct travel times in the simulation. |
| `test_simulation.py` | 27 | Incident releases, simultaneous events, initially busy responders, travel, treatment, locations, zero-duration jobs, deadlines and rejected assignments. |
| `test_scripted.py` | 6 | Script loading, request times, simultaneous requests, repeated decision times and invalid commands. |
| `test_allocation.py` | 21 | Priority order, responder conflicts, assignment constraints, response-time goals, real scenarios, solver statuses and time limits. |
| `test_statistics.py` | 9 | Response time including waiting, late and unhandled incidents, empty results and command-line execution. |
| `test_plan_validation.py` | 14 | Plan format, capabilities, releases, availability, repeated assignments, one-way roads, treatment, deadlines and invalid JSON. |
| `test_outputs.py` | 12 | Complete runs, exported files, departure times, printed results, menu choices, comparison folders and validator exit codes. |
| `test_diagnostics.py` | 12 | Changing reasons for unhandled calls, competing assignments, missing routes or skills, solver timeouts and unchanged planning results. |

To run one file:

```console
python -m unittest discover -s tests -p test_hmm.py -v
```

## Complete-system tests

The menu test runs the actual program for all three scenarios. It includes loading, Bayesian inference, HMM processing, routing, CP-SAT, simulation, validation and output generation. It checks the printed and saved files and the expected handled counts: **6, 11 and 13**.

The export test runs **18 combinations**: three scenarios, strict or late deadlines, and Bayesian-only, HMM tie-breaking or HMM bounded routing. Each plan is read back and checked against the simulation. The validator independently reconstructs travel, arrival, treatment completion and statistics from the original inputs.

Additional command-line tests check normal runs, scripts, comparisons and standalone validation. They verify file locations and exit codes. Route-only commands must not export assignment files.

Diagnostic tests compare recording on and off across all scenarios and both deadline modes. Assignments, times, event logs and existing statistics must remain identical. A separate development check compared 48 runs before and after the diagnostic change, with no differences in the original results.

## Independent checks

Expected results are not taken only from the function being tested:

- Bayesian probabilities are checked against hand calculations and separate probability sums.
- Forward is checked by trying every hidden-state sequence in small examples, including 27 sequences for three readings.
- Small CP-SAT models are checked by trying every compatible assignment combination.
- UCS and A* are compared on **1,690 scenario node pairs**: 845 with normal costs and 845 with Bayesian costs. Returned paths and travel sums are checked as well as minimum costs.
- Both search algorithms are also checked against every simple path in **750 small-graph cases**. Different equal-cost routes are allowed.
- Bounded traffic routing is checked against all possible simple paths on small graphs.

Solver tests include real solves and controlled cases for `FEASIBLE`, `UNKNOWN`, exhausted budgets and model errors. These verify that an unfinished solve is not reported as a proved optimum.

## Scenario results

The main settings are a **20% blockage cutoff**, **5% maximum extra travel**, **10% minimum traffic-score reduction**, and a **two-second solver budget per decision**. The solver uses one worker and seed zero.

Strict-deadline results:

| Scenario | CSP handled | Nearest handled | CSP on time | CSP mean response (seconds) |
| --- | ---: | ---: | ---: | ---: |
| 1 | 6/7 | 5/7 | 85.7% | 91.1 |
| 2 | 11/12 | 11/12 | 91.7% | 33.3 |
| 3 | 13/20 | 15/20 | 65.0% | 607.9 |

An incident is handled after treatment finishes. Mean response is arrival minus release, including waiting, for handled incidents only. The on-time percentage includes all incidents, including those left unhandled.

With late responses allowed, CSP handled all 7, 12 and 20 incidents but missed 2, 2 and 9 deadlines. Allowing late work can keep a responder occupied when another call appears.

In Scenario 3, an early choice between equal-cost responders changed which skills were available at which locations later. CSP optimizes the current allocation without planning several jobs ahead. The nearest-responder method produced better coverage in that run.

HMM bounded routing changed suggested routes for seven pairs of locations in Scenario 3. None of those journeys was used in the actual assignments. Committed routes, handled counts and deadline results therefore remained unchanged. No A* runtime comparison was performed.

The allocation comparison contains 12 runs. The traffic-policy comparison contains 36 runs, covering all scenarios, both allocators and both deadline modes. Reproduce them with:

```console
python benchmark.py --block-threshold .2
python benchmark_traffic.py --block-threshold .2 --max-extra-fraction .05 --min-exposure-reduction .10
```

Detailed results are saved in [allocation_comparison.json](results/allocation_comparison.json), [traffic_comparison.json](results/traffic_comparison.json) and [plan_export_validation.json](results/plan_export_validation.json). Generated plans and statistics are under `results/menu/` and `results/plans/`.

## Python compatibility

The Windows compatibility checks used OR-Tools 9.15.6755:

| Python version | Result |
| --- | --- |
| 3.12.14 | Fresh installation passed all 175 tests and all three menu runs. |
| 3.14.10 | Isolated installation passed all 175 tests and all three menu runs; plans were unchanged. |
| 3.15.2 | OR-Tools could not be installed. The suite attempted 175 tests and reported 60 missing-OR-Tools errors. |

The only direct third-party dependency is OR-Tools. Its dependencies are installed automatically. `python -m pip check` passed in both working environments. macOS and Linux execution has not been directly tested.

## Limits of the tests

Passing tests supports the behaviour checked here. It does not prove real-world safety, accurate traffic predictions or the best possible plan across future calls. No line or branch coverage percentage has been measured.

The plan validator rebuilds routes and timelines independently, but shares the Bayesian calculation with the application. Separate probability tests check that shared calculation. Tests of decision snapshots check that unreleased calls are not exposed to the allocator.

Actual blockages, rerouting, patient transport, station returns and Critical fallback are not implemented. The current tests do not establish how those proposed extensions would perform.
