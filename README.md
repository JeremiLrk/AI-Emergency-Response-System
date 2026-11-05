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

`run.py` loads and validates a scenario and prints its summary. `--route START GOAL`
returns a handwritten UCS route under an explicitly all-open, normal-speed baseline.
The Scenario1 example returns 48.06666666666667 seconds. It is not a dispatch plan.

## Files and scope

- `emergency_response/models.py`: typed scenario records and incident visibility.
- `emergency_response/loaders.py`: actual CSV/JSON schema parsing and validation.
- `emergency_response/graph.py`: directed weighted graph with road identities.
- `emergency_response/routing.py`: baseline or complete road-status snapshots.
- `emergency_response/search.py`: handwritten uniform-cost search.
- `tests/`: small targeted checks plus all-pairs checks on all three datasets.
- [Code walkthrough and explanation](CODE_GUIDE.md).
- [Actual schemas and data audit](DATA_SCHEMA.md).
- [Design decisions and course connections](DESIGN.md).
- [Tests and limits](TESTING.md).
- [LLM collaboration notes](LLM_NOTES.md).

Scenarios use metres, metres/second and seconds. Reports are available at time zero;
traffic observations are historical ordinal sequences for directed roads. Bayesian
road statuses and HMM traffic states are distinct. See the supplied
[scenario documentation](Scenarios/README.md).

This is the first implementation checkpoint. Bayesian inference, HMM filtering,
OR-Tools allocation, simulation and final plan validation are deferred. The required
final `plan.json` and `statistics.txt` are not generated yet. Do not submit this as
the completed assignment.
