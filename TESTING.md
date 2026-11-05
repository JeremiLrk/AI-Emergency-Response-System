# Verification of this checkpoint

Run from the repository root with Python 3.10+:

```console
python -m unittest discover -s tests -v
python run.py Scenarios/Scenario1 --route H1 N2
python run.py Scenarios/Scenario2
python run.py Scenarios/Scenario3
```

Seventeen tests cover:

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

These checks do **not** establish full-plan validity, scheduling feasibility,
probabilistic calibration, Bayesian/HMM correctness or solver performance.
No plan or handled-incident statistics are generated at this stage.
