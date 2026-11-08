# Verification of this checkpoint

Run from the repository root with Python 3.10+:

```console
python -m unittest discover -s tests -v
python run.py Scenarios/Scenario1 --route H1 N2
python run.py Scenarios/Scenario2
python run.py Scenarios/Scenario3
```

The original seventeen foundation tests still cover:

* Handwritten UCS: cheaper indirect routes, goal testing on removal, stale heap
  entries, disconnected/directed graphs, parallel edges, zero-cost cycles,
  start=goal, invalid nodes and costs.
* Raw readers: BOMs, string IDs, quoted CSV fields, malformed rows/headers,
  duplicate JSON keys and nonstandard numeric constants.
* All three real schemas, expected counts, units, capability splitting,
  initial availability and time-based incident visibility.
* All **845** ordered node pairs (25+144+676) under normal all-open costs,
  compared with an independent Bellman-Ford relaxation calculation. Returned
  route endpoints, directed road IDs, adjacency and summed cost are checked.
* Caller-supplied Blocked/Congested road snapshots and direction separation.
* Corrupted fixtures: unknown endpoint, zero speed, conflicting local weather,
  duplicate historical index, inconsistent availability, invalid probability
  labels/ranges/sums; also reversed history ordering and fractional availability.
* Deadline-before-release is retained as a warning rather than silently changed.

Baseline Scenario1 H1 -> N2 returns the direct road, 48.06666666666667 seconds.
This ignores noisy blockage reports and traffic deliberately; it demonstrates
unit-correct routing, not a valid dispatch decision under uncertain conditions.

The additional Bayesian/policy tests below check model arithmetic and integration.
They do **not** establish full-plan validity, scheduling feasibility, real-world
probabilistic calibration, HMM correctness or solver performance. No plan or
handled-incident statistics are generated at this stage.


## Bayesian checkpoint: 39 tests total

```console
python -m unittest discover -s tests -v
python run.py Scenarios/Scenario1 --route N1 N2 --routing-policy bayesian --block-threshold 0.2
```

All 17 existing tests and 22 new tests pass. New coverage includes manually
calculated conflicting/reverse-road posteriors, known/unknown weather, no/partial
reports, explicit full-joint enumeration summing out missing evidence, evidence
order invariance, no input mutation, all-road scenario coverage, local weather,
invalid inputs and zero-likelihood diagnostics. Scenario copies constructed
directly also reject duplicate reports and conflicting weather.

Policy tests check conditional-time normalization, threshold boundaries, certain
blockages, missing/invalid beliefs, directed exclusions, no-route cases, static
repeated-road bounds and start=goal. A constructed two-edge example shows an
edge threshold is not a route risk cap. Another example verifies the policy can
choose a faster, riskier route over a slower safer one; this limitation is visible
and intentional, not silently called a safest-route algorithm. CLI tests confirm
full distributions/risk bounds and explicit policy selection.

All 845 ordered node pairs are also compared with independent Bellman-Ford
relaxation on Bayesian threshold-.2 graphs, in addition to the original 845
baseline comparisons. Unreachable results are checked as well as finite costs.

Verified Scenario1 N1->N2:

| Policy | Route | Travel score (s) | Modeled blockage bounds |
| --- | --- | ---: | --- |
| All-open baseline | N1->N2 | 51.6666666667 | .5268817204 to .5268817204 |
| Bayesian threshold .20 | N1->H1->N2 | 86.7780346821 | .135 to .27 |
| Bayesian threshold .10 | None | N/A | N/A |

The Bayesian score sums per-edge expected times conditional on each edge being
traversable. It is not an unconditional expected arrival. The bounds require no
cross-road independence, but remain conditional on the correctness of the model.

## Measured threshold sensitivity on supplied datasets

These are graph reachability checks, not dispatch outcomes. Pairs exclude
start=goal. Thresholds are illustrative and are never silently adjusted.

| Scenario | Threshold | Retained edges | Reachable distinct pairs |
| --- | ---: | ---: | ---: |
| Scenario1 | .10 | 2/14 | 3/20 |
| Scenario1 | .20 | 10/14 | 20/20 |
| Scenario1 | .50 | 10/14 | 20/20 |
| Scenario1 | .90 | 12/14 | 20/20 |
| Scenario2 | .10 | 12/30 | 16/132 |
| Scenario2 | .20 | 28/30 | 60/132 |
| Scenario2 | .50 | 28/30 | 60/132 |
| Scenario2 | .90 | 30/30 | 132/132 |
| Scenario3 | .10 | 12/60 | 20/650 |
| Scenario3 | .20 | 58/60 | 650/650 |
| Scenario3 | .50 | 58/60 | 650/650 |
| Scenario3 | .90 | 60/60 | 650/650 |

Scenario2's .20 policy removes N1->N2 and N2->N1 (posterior blockage .8301957831
each), disconnecting parts of the planning graph. A stricter threshold can make
valid real-world routes unavailable to the planner; a permissive one can retain
substantial risk. No true-state files are supplied, so these data cannot establish
which policy is actually safer or measure forecast calibration.


## Simulation checkpoint: 72 tests total

All 39 existing tests and 33 new simulation/script tests pass. Run:

```console
python -m unittest discover -s tests -v
python run.py Scenarios/Scenario1 --simulate-script examples/scenario1_script.json --routing-policy bayesian --block-threshold 0.2
```

Simulation tests cover batched simultaneous releases, completion+release equality,
updated departure locations, initially busy readiness (including zero), travel
followed by service, positive/zero durations, chained zero jobs at an exact
deadline, inclusive arrival deadlines, and service finishing after a deadline.
They also cover strict rejection/closure, late departure and late completion with
independent missed outcomes, unreachable work, empty decisions, future releases,
past-deadline releases, fractional and near-but-distinct timestamps, explicit
wake-ups, finite empty-input termination and unrepresentable float time advances.

Snapshot tests inspect every revealed timestamp/candidate ID, verify no Scenario
or event queue is exposed, and attempt mutation of frozen views. They also verify
earlier snapshots and original inputs/graph stay unchanged. Invalid duplicate
responder/incident batches are checked for zero partial commits. Premature,
unqualified and busy dispatches are rejected; new critical incidents do not
preempt an already travelling responder.

Script/CLI tests cover parsing, simultaneous grouping, input copying, consume-once
behavior, malformed times/IDs/options, full Bayesian+simulation JSON and allow-late
completed/missed outcomes. All three real scenarios run with a no-op dispatcher in
strict and late modes: all incidents are revealed and explicitly unhandled/missed,
with finite termination. This verifies stream mechanics, not allocation quality.

The real Scenario1 script completes four incidents, all with modeled deadlines met;
three are explicitly closed_unassigned/missed. Final event is I5 completion at
217.3471400394 seconds. Its arrival is 197.3471400394, before deadline 200. R4's
initial busy state lasts to 10, then its I1 arrival is 66.9687861272. R1 finishes
I2 at 116.7780346821, remains at N2, and departs for I5 at scripted time 120.

An independent replay test checks each real-script commitment's release,
capability, initial/later availability, updated location, graph adjacency/road ID,
summed edge time, arrival deadline, treatment duration and incident uniqueness.
This adds evidence beyond asserting engine output fields; it is not yet a general
standalone plan-validator module or empirical validation of uncertain travel.

Limitations: scripts are fixtures, not an allocation algorithm; no solver/HMM or
final plan/statistics files are implemented. Execution follows estimates without
sampled road truth or unexpected delay. A completed/met modeled job is therefore
not evidence of guaranteed real-world safety or calibrated forecast performance.


## CP-SAT checkpoint: 102 tests total

Use the project virtual environment and pinned dependency:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe benchmark.py --block-threshold 0.2
```

All 72 existing tests plus 30 new allocation/statistics/CLI tests pass. Two old
CLI rejection cases were updated because normal runs now execute automatically:
Bayesian mode with a supplied threshold no longer requires --route/script, and
--allow-late is valid for normal execution. Their replacement cases still check
missing Bayesian thresholds and meaningless --allow-late in route-only mode;
new positive tests cover the changed default/late interfaces.

New tests cover priority versus faster lower-priority response, absence of deadline
ranking, response including dispatch waiting, joint assignment preserving a flexible
unit, choosing between responders, optional unassigned work, on-time preference
after priority coverage in late mode, snapshot/immutability/future checks, integer
precision and budget validation. Independent exhaustive subset enumeration checks
the full objective on small models and actual Scenario2's seven initial candidates.

Controlled mocked solver outcomes test FEASIBLE, UNKNOWN before/after an incumbent,
shared-budget exhaustion between phases, zero budget, MODEL_INVALID and INFEASIBLE.
They verify that values are never read without a feasible solution, unproven
priority counts are never fixed as optimal, previous valid solutions are retained,
and model errors are not disguised as no feasible emergencies. Real solver tests
verify actual constraints/objectives; mocked tests target status-control branches.

All three real scenarios run under both allocators and both deadline policies.
An independent replay checks every commitment's incident release, capability,
readiness/nonoverlap, updated origin, graph edge IDs/costs, arrival and treatment
times, strict deadlines and uniqueness. The allocator wrapper inspects every
snapshot for early incident exposure. Metrics tests cover empty/no-handled runs,
late-completed versus on-time counts, all/handled denominators and waiting time.

### Measured comparison

Bayesian threshold .20, CP-SAT shared budget 2s/decision, response precision 1ms,
one worker/seed 0, fixed modeled execution. Average response uses completed work
only. All CP-SAT decisions were proven optimal or trivially had no candidates;
there were no time-limit fallbacks in this evaluation. Nearest uses no solver.

| Scenario | Deadline mode | Allocator | Handled | Deadlines met | Avg response (s) |
| --- | --- | --- | ---: | ---: | ---: |
| Scenario1 | strict | csp | 6/7 | 6/7 | 91.113 |
| Scenario1 | strict | nearest | 5/7 | 5/7 | 82.438 |
| Scenario1 | allow_late | csp | 7/7 | 5/7 | 102.276 |
| Scenario1 | allow_late | nearest | 7/7 | 5/7 | 98.938 |
| Scenario2 | strict | csp | 11/12 | 11/12 | 33.253 |
| Scenario2 | strict | nearest | 11/12 | 11/12 | 33.253 |
| Scenario2 | allow_late | csp | 12/12 | 10/12 | 32.782 |
| Scenario2 | allow_late | nearest | 12/12 | 10/12 | 32.782 |
| Scenario3 | strict | csp | 13/20 | 13/20 | 607.937 |
| Scenario3 | strict | nearest | 15/20 | 15/20 | 586.235 |
| Scenario3 | allow_late | csp | 20/20 | 11/20 | 1408.182 |
| Scenario3 | allow_late | nearest | 20/20 | 12/20 | 1378.635 |


Reproduce using benchmark.py; results/allocation_comparison.json contains all
unrounded metrics, per-priority counts, configurations, status/proof counts and
commitments. An exact JSON-normalized repeat matched all of those fields.

Interpretation: Scenario1 strict CSP serves an additional Critical incident; its
higher mean is not directly comparable to nearest's smaller handled subset.
Scenario2 ties. Scenario3 strict nearest serves two more Critical incidents than
the locally optimal CSP run; the initial equal-cost responder tie changes later
Medical emergency coverage. With late responses, all incidents are completed in
these examples, but deadline counts can be worse than strict mode because earlier
late commitments consume resources. Local optimality never implies a globally
optimal event sequence or best real-world outcome.

No EDF/rank term was added to fix disappointing results, and no threshold was
silently relaxed. Tie outcomes are pinned only by tested environment/configuration,
not promised identical across all OR-Tools versions. This earlier comparison has
no HMM preference or hidden-road execution; these statistics are modeled outcomes and no standalone final
submission-format plan/statistics files are generated yet.

## Historical HMM checkpoint: 121 tests total

The earlier 102 tests still pass, unchanged. Nineteen new tests cover:

- Actual Scenario2 H2->N8 numerical results at all five prefixes, using the
  supplied initial, transition and emission tables (see DESIGN.md for numbers).
- Independent enumeration of all 27 hidden paths for a three-observation example,
  confirming Forward sums paths rather than selecting a maximum sequence.
- Scenario-specific missing-history priors, reverse-road separation, normalization,
  all-road coverage and counts, input immutability and sorting by historical ordinal.
- Invalid history references/indices, invalid state vocabulary, zero-likelihood
  evidence, and normalization of 10000 observations without sequence underflow.
- Exact-time ties versus near ties; explicit travel allowance and exposure gate;
  multiple Pareto labels at a shared node; zero-cost cycles and unreachable roads.
- Independent exhaustive simple-path enumeration on 30 seeded small DAGs, checking
  the bounded optimum and acceptance gate, plus explicit label-limit errors.
- Directed metadata checks and CLI bounded-route output/configuration rejection.
- Actual graph all-pairs checks: exact tie preserves minimum travel; bounded time
  stays within 5%; every returned duration equals original graph edge sums and
  graphs remain unchanged. This does not claim real-world travel calibration.
- Simulator selected route travel=21, treatment=7 => arrival21/completion28,
  rather than using exposure2.1. With deadline20.5 strict mode keeps shortest20;
  late mode accepts21 and records missed. A forged zero duration is rejected.

Run from repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe benchmark_traffic.py --block-threshold .2 --max-extra-fraction .05 --min-exposure-reduction .10
```

The full suite passes: 121 tests. No existing tests were removed or weakened.
Python3.12.14 / OR-Tools9.15.6755. HMM calculations use Python standard library;
the only solver dependency remains the previously pinned OR-Tools package.

### Fixed-parameter comparison on all three scenarios

Before evaluation, maximum extra travel=.05 and minimum exposure reduction=.10
were declared. Bayesian blockage threshold=.20 remains the previous comparison
setting. Solver budget2s, one worker, seed0, response scale1000 remain unchanged.
No tuning after seeing results. Report: results/traffic_comparison.json, containing
36 fresh runs (3 scenarios x 2 deadline modes x 2 allocators x 3 route policies),
complete assignments, per-assignment exposures/time detours/blockage bounds,
priority counts, solver status and explicit changes from Bayesian-only.

For EVERY row below, Bayesian-only, hmm-tie and hmm-bounded produce the same
assignments, routes, departures, handled counts, met counts and average responses:

| Scenario | Mode | Allocator | Handled/total | Met/total | Mean response seconds |
| --- | --- | --- | ---: | ---: | ---: |
| 1 | strict | CSP | 6/7 | 6/7 | 91.113 |
| 1 | strict | nearest | 5/7 | 5/7 | 82.438 |
| 1 | allow late | CSP | 7/7 | 5/7 | 102.276 |
| 1 | allow late | nearest | 7/7 | 5/7 | 98.938 |
| 2 | strict | CSP | 11/12 | 11/12 | 33.253 |
| 2 | strict | nearest | 11/12 | 11/12 | 33.253 |
| 2 | allow late | CSP | 12/12 | 10/12 | 32.782 |
| 2 | allow late | nearest | 12/12 | 10/12 | 32.782 |
| 3 | strict | CSP | 13/20 | 13/20 | 607.937 |
| 3 | strict | nearest | 15/20 | 15/20 | 586.235 |
| 3 | allow late | CSP | 20/20 | 11/20 | 1408.182 |
| 3 | allow late | nearest | 20/20 | 12/20 | 1378.635 |

There are zero added/removed assigned incidents, changed responders, changed
committed routes or departures, and zero committed detours, for both HMM policies
against their matching Bayesian-only run. All CSP decision hierarchies were
proven; no unproven fallback explains the unchanged result. Means are over
completed incidents, include release-to-dispatch waiting, and exclude treatment.
Different allocator coverage still makes means alone an incomplete comparison.

The broader all-pairs audit includes reachable start=goal pairs:

| Scenario | Reachable pairs | Exact-tie route changes | Bounded route changes |
| --- | ---: | ---: | ---: |
| 1 | 25 | 0 | 0 |
| 2 | 72 | 0 | 0 |
| 3 | 676 | 0 | 7 |

Seven changed directed pairs are N3->H1, H1->N1, H1->N3, H1->N7, H1->N20,
H1->P1 and P1->H1. These are not routes committed by either allocator in either
deadline mode. A concrete example is N3->H1:

- Shortest: N3-N4-N9-H1, 1302.620309 seconds, exposure112.653333.
- Bounded: N3-N5-N8-H1, 1331.570578 seconds, exposure62.005453.
- Extra time28.950269 seconds (about2.22%, within5%); exposure falls44.96%,
  above the required10%. The new route duration is1331.570578, NOT62.005453.

The opposite direction has different exposure reduction because histories are
directed. The report preserves all seven alternatives for inspection. Synthetic
tests establish policy behavior even where these three simulations do not use
the affected endpoints. There is no evidence here of improved emergency outcomes;
do not increase the allowance retrospectively to manufacture improvement.

Limitations: historical beliefs have unknown age, no live evidence, no hidden
traffic/road truth or recovery simulation, no traffic calibration, and no proof
that historical High exposure measures actual safety. A lower score can increase
route-level blockage bounds. Strict travel feasibility is preserved, but allowing
late responses can let a detour miss a previously achievable deadline. The
allocator sees one route per pair; this is not joint route/allocation optimization.
The bounded search is exact under its finite floating-cost model when it finishes,
but can hit its explicit label guard on larger graphs. Existing Scenario3 CSP
versus nearest underperformance is preserved and explained above.

## Required outputs and independent plan validation: 145 tests total

Assignment sections5.1/5.2 were checked against the provided PDF before changing
run.py. Scenarios/README.md confirms fractional seconds, dispatch start times and
historical observations. The exact list/row schema is tested; required plan rows
have only responder_id,incident_id,path,time. Statistics definitions are unchanged.

The full suite passes145 tests (previous121 plus24). Existing CLI tests now use
temporary --output-dir locations because execution intentionally writes artifacts;
their previous behavioral assertions remain. No tests were removed or weakened.
Temporary test outputs are contained beneath tests/ and cleaned up automatically.

New tests cover:

- Original-data reconstruction: travel5, treatment2, deadline5 means arrival5
  meets the deadline even though completion7 is later.
- Empty valid plans versus poor coverage, N/A response mean, zero/all-incident
  deadline percentage, and N/A for an empty incident stream.
- Exact list/row schema; unknown IDs/nodes; empty/non-list paths; extra fields;
  negative, boolean, nonnumeric, huge/unrepresentable and nonfinite start times.
- Strict JSON decoding rejects duplicate keys, malformed JSON and NaN/Infinity.
- Duplicate incidents, including two different responders assigned the same call.
- Capability, release and initially busy checks, including exact readiness time.
- Directed roads, initial/current path endpoints, and location after earlier work.
- One responder handling consecutive incidents: next dispatch must wait through
  travel AND treatment; exact completion reuse and zero-duration same-time reuse
  are allowed. Chronologically unsorted plan rows are replayed correctly.
- Bayesian conditional travel6.875 from controlled original-road time5 and beliefs
  (.2,.6,.2), and rejection at the exact blockage threshold. The validator uses
  its own road cost reconstruction rather than a trusted graph.
- Strict late-arrival rejection versus explicit late-policy warnings/compliance.
- No simulator/UCS/graph-builder calls during validation (patched to fail if used).
- Tampered simulation travel, arrival, completion or final statistics cause export
  rejection BEFORE writing either file.
- Departure/start3 differs from release1 and arrival8; response7 includes waiting,
  treatment finishes10; exported time remains3.
- CLI writes required names, default working-directory behavior, separate comparison
  output directories, script export, route-only no-export and standalone exit codes.
- A scripted late export validates only with explicit --allow-late; strict validation
  fails with deadline errors, while the late report remains deadline_compliant=false.

Actual-scenario integration covers18 simulations (3 scenarios x strict/late x
Bayesian-only/tie/bounded policies). Each file is read back; every path/time equals
the corresponding simulation commitment; independent arrival/completion and
Statistics equal the execution output. Tests assert expected handled/deadline
counts and responders reused across multiple incidents. Both unhandled strict
calls and completed late calls are covered.

### Saved CLI exports

results/plans/ScenarioN/strict and allow_late contain six generated plan/statistics
pairs. They use CSP, Bayesian threshold.20, bounded allowance.05, minimum exposure
reduction.10, default2s solver budget, worker1/seed0. These unchanged settings were
not tuned for this task. results/plan_export_validation.json records standalone
validator results and file-versus-stdout agreement for all six CLI runs.

| Scenario | Mode | Handled | Met | Mean response seconds | Policy-valid | All assigned arrivals on time |
| --- | --- | ---: | ---: | ---: | --- | --- |
| 1 | strict | 6/7 | 6 | 91.113 | yes | yes |
| 1 | allow late | 7/7 | 5 | 102.276 | yes | no |
| 2 | strict | 11/12 | 11 | 33.253 | yes | yes |
| 2 | allow late | 12/12 | 10 | 32.782 | yes | no |
| 3 | strict | 13/20 | 13 | 607.937 | yes | yes |
| 3 | allow late | 20/20 | 11 | 1408.182 | yes | no |

Strict plans are feasible under the declared travel estimates while leaving
1,1,7 incidents unhandled. Late plans complete all incidents but do not satisfy
every assignment arrival deadline; the relaxed-policy label is essential.
Exporting does not alter routing/allocation/timing or prior benchmark findings.
An empty or partial plan may be valid without good performance. The primary
deadline denominator remains all incidents, so omissions are never rewarded.

Replay is independent of simulator state/timing helpers/graph/search/allocator,
but reuses the tested Bayesian inference and Statistics data container. It is
therefore not an independent proof of probability inference, true road conditions
or calibration. The fixed JSON schema contains no reported arrival/treatment
durations; validation reconstructs them, and export compares them with the richer
simulation records. Absence of future-aware decision making cannot be established
from the final plan alone; existing snapshot-boundary tests address that separately.

No final report.pdf exists yet. The maximum3-content-page report (optional extra
prompt page), prominent GitHub link, required repository access/submission and
oral defence preparation remain deliverables. Real road-failure recovery/live
traffic/optimal full-horizon planning are documented limitations, not additional
mandatory features invented by this task.
