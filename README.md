# AI-Emergency-Response-System
Artificial Intelligence Practicum — Emergency response planning using search, Bayesian reasoning, constraint satisfaction, and Hidden Markov Models.

First Prompt:

I've attached my AI practicum assignment, the scenarios and the course slides.

From what I understand, we need to build a system that assigns emergency responders to incidents and finds suitable routes, while taking into account deadlines, responder availability and uncertain road conditions.

We need to combine search, CSPs, Bayesian reasoning and HMMs to do this. Before starting the implementation, I want to figure out how these components should work together and how to structure the project.

Since the assignment is open-ended, I'd like to discuss the possible approaches and important design decisions first. Use the course slides as the main reference, but feel free to suggest alternatives and point out problems with my approach.

The goal is to build a working system that I can fully understand, test and defend afterwards.


## Install and run

Use Python 3.11/3.12 (tested 3.12.14) and the pinned OR-Tools requirement. A local
.venv has already been created on this laptop. For a new checkout on Windows:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Normal runs now allocate online with CP-SAT; no script is needed:

```powershell
.\.venv\Scripts\python.exe run.py Scenarios/Scenario1 --routing-policy bayesian --block-threshold 0.2
```

The .2 threshold is illustrative, never a built-in safe default. Omitting
--routing-policy bayesian retains the original all-open routing baseline.
Normal allocation defaults to CP-SAT, which maximizes assignments by priority,
prefers on-time responses in late mode, then minimizes predicted response time.
There is no deadline ranking. --solver-time-limit controls the shared per-decision
wall budget (default 2 seconds); statuses/proof/fallbacks are printed explicitly.

Other modes:

```powershell
# Compare CSP and greedy nearest on the same graph and deadline policy
.\.venv\Scripts\python.exe run.py Scenarios/Scenario1 --compare --routing-policy bayesian --block-threshold 0.2
# Enable late responses while recording deadline misses independently
.\.venv\Scripts\python.exe run.py Scenarios/Scenario1 --allow-late --routing-policy bayesian --block-threshold 0.2
# Run all three scenarios, strict and late, and save comparison JSON
.\.venv\Scripts\python.exe benchmark.py --block-threshold 0.2
# Keep scripted fixtures and route-only inspection
.\.venv\Scripts\python.exe run.py Scenarios/Scenario1 --simulate-script examples/scenario1_script.json --routing-policy bayesian --block-threshold 0.2
.\.venv\Scripts\python.exe run.py Scenarios/Scenario1 --route N1 N2 --routing-policy bayesian --block-threshold 0.2
```

--allocator nearest selects one normal greedy run. --route, --simulate-script
and --compare are mutually exclusive; --allow-late applies to execution modes.
An invalid script/model aborts visibly. Unknown/limited solver runs retain an
earlier valid incumbent if available and never call a timeout proof of no work.

## Files

- emergency_response/models.py and loaders.py: validated scenario input.
- graph.py, search.py, routing.py: fixed graphs, handwritten UCS and all-open/status adapters.
- bayesian.py and risk_routing.py: full road posteriors, threshold policy and risk bounds.
- simulation.py and simulation_models.py: event controller and immutable snapshot API.
- scripted.py: mechanical dispatch fixtures, not an allocation policy.
- allocation.py: Boolean CP-SAT dispatcher and solver diagnostics.
- baseline.py: nearest-feasible greedy comparison dispatcher.
- statistics.py: modeled coverage, deadline denominators and response-time means.
- benchmark.py and results/allocation_comparison.json: reproducible comparisons.
- hmm.py and traffic_routing.py: historical Forward beliefs and separate route criteria.
- benchmark_traffic.py and results/traffic_comparison.json: fixed-parameter HMM comparison.
- outputs.py and plan_validation.py: required files and independent original-data replay.
- validate_plan.py: standalone read-only validator.
- tests/: 145 checks of inference, routing, simulation, optimization, exports and validity.
- [Code explanation](CODE_GUIDE.md), [schemas](DATA_SCHEMA.md), [design](DESIGN.md),
  [verification/results](TESTING.md), [LLM collaboration](LLM_NOTES.md).

## Interpretation and scope

The simulator reveals incidents at their timestamps and passes current snapshots
only. The dispatcher cannot reserve busy responders or change committed jobs.
Locations update after travel and remain at the incident after service. Strict
arrival deadlines are a baseline; completed work can remain deadline-missed in
late mode. Times are seconds. Travel is a deterministic modeled estimate; route
blockage bounds do not certify actual arrival or safety. Required plan/statistics
files and independent validation are implemented; real-road failure/recovery remains
unmodeled. The final report.pdf, GitHub submission/access and defence preparation
still need completion.

All 145 tests pass. At threshold .20, strict CSP handles 6/7, 11/12, 13/20 in the
three scenarios; nearest handles 5/7, 11/12, 15/20. Local optimization does not
guarantee better whole-run coverage. Read TESTING.md for means, late-mode results
and the observed equal-cost placement limitation. No disappointing result is hidden.

## Historical traffic policies

Forward filtering processes each directed road's historical observations once;
missing histories retain the scenario's own prior. Bayesian travel estimates are
unchanged. Traffic exposure is sum(normal seconds * historical P(High)), a
separate preference score, never a travel duration or safety guarantee.

```powershell
# Exact shortest-time tie-breaker
.\.venv\Scripts\python.exe run.py Scenarios/Scenario3 --routing-policy bayesian --block-threshold .2 --traffic-policy hmm-tie
# At most 5% extra travel, requiring at least 10% lower exposure
.\.venv\Scripts\python.exe run.py Scenarios/Scenario3 --routing-policy bayesian --block-threshold .2 --traffic-policy hmm-bounded --max-extra-fraction .05 --min-exposure-reduction .10
# Same settings, all scenarios, both allocators and deadline modes
.\.venv\Scripts\python.exe benchmark_traffic.py --block-threshold .2 --max-extra-fraction .05 --min-exposure-reduction .10
```

Omitting --traffic-policy preserves original Bayesian-only UCS when Bayesian
routing is selected; the existing all-open routing baseline is also available.
For strict deadlines, route detours must also fit the remaining arrival budget.
Selected travel seconds still determine arrivals, deadlines and availability.
The fixed comparison changes seven all-pairs routes in Scenario3, but no routes
actually dispatched in the 36 runs; outcome metrics are unchanged. Parameters
were not increased to produce a better result. See DESIGN.md for formulas and
TESTING.md for the full table, worked example and limitations.

## Required output files and independent validation

A normal run now writes plan.json and statistics.txt to the current directory.
Use --output-dir to keep runs separate. Full-system example using all four AI
components, with the existing fixed traffic settings:

```powershell
.\.venv\Scripts\python.exe run.py Scenarios/Scenario1 --routing-policy bayesian --block-threshold .2 --traffic-policy hmm-bounded --max-extra-fraction .05 --min-exposure-reduction .10 --output-dir results/plans/Scenario1/strict
.\.venv\Scripts\python.exe validate_plan.py Scenarios/Scenario1 results/plans/Scenario1/strict/plan.json --routing-policy bayesian --block-threshold .2
```

The exact required plan structure is a list of
`{"responder_id":"R1","incident_id":"I1","path":["N1","N2"],"time":0}`
objects. The example illustrates fields, not feasibility for a specific scenario.
time is the recorded dispatch/start in seconds; path contains node IDs. No extra
wrapper or fabricated arrival-time fields are added. Unhandled incidents are
absent from plan rows and explicitly counted/listed in statistics.txt.

statistics.txt reports completed incidents, distinct responders, mean arrival-minus-
release response and on-time arrivals/all incidents percentage. Unhandled incidents
count as not met and are excluded from the response mean. Empty means/denominators
are N/A. Units, assumptions and generation configuration are recorded in the text.

The validator recomputes paths, travel, treatment, readiness and deadlines from
original data, without calling the simulator/search/allocator. Generation checks
that reconstructed values and statistics agree before writing. Standalone exit
codes:0 valid under selected policy,1 invalid plan,2 malformed input/configuration.
Give it the same routing policy/threshold recorded in statistics.txt. HMM settings
do not alter travel-cost validity and are not needed by the validator.

--allow-late remains an experimental policy. It must also be given to the standalone
validator for those plans; policy-valid late plans can violate assignment arrival
deadlines and are explicitly labeled. Strict is the default. A valid empty/partial
plan can perform poorly; validation does not prove optimality or actual safety.

--compare writes separate csp/ and nearest/ subdirectories beneath --output-dir.
Script runs also export their commitments. Diagnostic --route writes no plan or
statistics because it does not execute incident assignments. Existing default
all-open routing and Bayesian-only UCS remain available for comparisons.

Saved strict/late examples for all three scenarios are under results/plans/;
results/plan_export_validation.json records original-data standalone replay and
matching simulation statistics. To regenerate all six sets:

```powershell
foreach ($scenarioNumber in 1..3) {
    .\.venv\Scripts\python.exe run.py "Scenarios/Scenario$scenarioNumber" --routing-policy bayesian --block-threshold .2 --traffic-policy hmm-bounded --max-extra-fraction .05 --min-exposure-reduction .10 --output-dir "results/plans/Scenario$scenarioNumber/strict"
    .\.venv\Scripts\python.exe run.py "Scenarios/Scenario$scenarioNumber" --routing-policy bayesian --block-threshold .2 --traffic-policy hmm-bounded --max-extra-fraction .05 --min-exposure-reduction .10 --allow-late --output-dir "results/plans/Scenario$scenarioNumber/allow_late"
}
```
