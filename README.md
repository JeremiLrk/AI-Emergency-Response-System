# AI-Emergency-Response-System
Artificial Intelligence Practicum — Emergency response planning using search, Bayesian reasoning, constraint satisfaction, and Hidden Markov Models.

First Prompt:

I've attached my AI practicum assignment, the scenarios and the course slides.

From what I understand, we need to build a system that assigns emergency responders to incidents and finds suitable routes, while taking into account deadlines, responder availability and uncertain road conditions.

We need to combine search, CSPs, Bayesian reasoning and HMMs to do this. Before starting the implementation, I want to figure out how these components should work together and how to structure the project.

Since the assignment is open-ended, I'd like to discuss the possible approaches and important design decisions first. Use the course slides as the main reference, but feel free to suggest alternatives and point out problems with my approach.

The goal is to build a working system that I can fully understand, test and defend afterwards.


## Running the foundation

Python 3.10+; standard library only. OR-Tools will be added for allocation later.
Run these commands from this repository's root:

```console
python -m unittest discover -s tests -v
python run.py Scenarios/Scenario1 --route H1 N2
python run.py Scenarios/Scenario2
python run.py Scenarios/Scenario3
```

`run.py` prints a scenario summary and full Bayesian probability distributions
for every directed road. `--route START GOAL` retains the all-open baseline
unless the Bayesian routing policy is explicitly selected. For example:

```console
python run.py Scenarios/Scenario1 --route N1 N2 --routing-policy bayesian --block-threshold 0.2
```

This excludes edges with P(Blocked)>=.2 and uses conditional expected edge
travel times, preserving the full beliefs. It prints route blockage bounds.
The threshold is illustrative, not a safety guarantee or built-in default.
This example takes N1->H1->N2 with score 86.778 seconds and blockage bounds
13.5%-27%. This route-only mode does not assign responders. Scripted execution is available below.

## Files and scope

- `emergency_response/models.py`: typed scenario records and incident visibility.
- `emergency_response/loaders.py`: actual CSV/JSON schema parsing and validation.
- `emergency_response/graph.py`: directed weighted graph with road identities.
- `emergency_response/routing.py`: baseline or complete road-status snapshots.
- `emergency_response/search.py`: handwritten uniform-cost search.
- `emergency_response/bayesian.py`: full road posteriors via exact inference.
- `emergency_response/risk_routing.py`: explicit edge-risk policy and route bounds.
- `emergency_response/simulation.py`: private event controller and public simulate API.
- `emergency_response/simulation_models.py`: immutable dispatcher views and results.
- `emergency_response/scripted.py`: explicit test fixtures, not an allocator.
- `tests/`: 72 checks including event mechanics and all-pairs routing comparisons.
- [Code walkthrough and explanation](CODE_GUIDE.md).
- [Actual schemas and data audit](DATA_SCHEMA.md).
- [Design decisions and course connections](DESIGN.md).
- [Tests and limits](TESTING.md).
- [LLM collaboration notes](LLM_NOTES.md).

Scenarios use metres, metres/second and seconds. Reports are available at time zero;
traffic observations are historical ordinal sequences for directed roads. Bayesian
road statuses and HMM traffic states are distinct. See the supplied
[scenario documentation](Scenarios/README.md).

This checkpoint includes Bayesian routing and scripted event simulation. HMM
filtering, OR-Tools allocation and standalone final plan validation remain deferred. The required final `plan.json` and `statistics.txt` are not generated yet. Do not submit this as
the completed assignment.


## Run the scripted event simulation

```console
python run.py Scenarios/Scenario1 --simulate-script examples/scenario1_script.json --routing-policy bayesian --block-threshold 0.2
```

Each JSON script record contains `time`, `responder_id`, `incident_id`. Same-time
records form one batch. The example requests four assignments and uses explicit
wake-up at 120 for its last departure. It completes four modeled incidents; it
does not optimize coverage of all seven. Invalid/premature requests raise errors.

Strict modeled arrival deadlines are the default. Add `--allow-late` to permit late
responses while recording deadline misses separately from completed treatment.
Without `--routing-policy bayesian`, simulation uses the original all-open graph.
Bayesian mode always requires an explicit threshold; .2 is only illustrative.
`--route` and `--simulate-script` are separate modes and cannot be combined.

Output includes full road beliefs, commitments, final incident/responder states,
deadline results, event log and per-assignment blockage bounds. It follows fixed
estimated travel durations, not hidden true road failures. No CSP is implemented.
Final submission-format plan.json/statistics.txt generation remains a later step.
