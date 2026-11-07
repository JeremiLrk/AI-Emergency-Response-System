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
