# Design decisions and boundaries

This checkpoint implements loading/validation, exact Bayesian road inference,
probability-aware graph construction, route blockage bounds, handwritten UCS and
script-driven event simulation. HMM inference, OR-Tools allocation and final
dispatch/statistics file generation remain deferred. Future work is labelled.

## Evidence and corrections to the earlier chat

Sources: supplied `Scenarios/README.md`, all seven input files in each of the
three scenarios, the assignment (`Assignment1 (1).pdf`, pp. 1-6), and course
search, CSP, Bayesian-network and HMM slides. See `DATA_SCHEMA.md` for the actual
schemas and counts. Scenario data and its README settle the previously missing
units and timing semantics.

The earlier proposal incorrectly suggested HMM states Open/Congested/Blocked
and incoming traffic observations. Correct those to traffic Low/Medium/High
and **pre-simulation history**. An HMM observation index is not a second or an
event timestamp. Do not simulate the historical rows as new observations.

The earlier risk expression combining normal time and a blockage penalty is
not an expected arrival time. It could even make a high-blockage road appear
faster if its penalty is too small. Do not use it for deadline checks.

## Data flow

`load_scenario` -> typed `Scenario` -> `infer_scenario` -> full road distributions
-> `build_bayesian_graph` -> `ucs` -> `Route` plus `route_blockage_bounds`.
The original all-open graph remains available for comparison.

The loader parses future input, but the simulator creates incident views only
when processing their release events. It passes no Scenario/event queue/future
records to a dispatcher. `known_incidents(now)` remains a useful standalone view. Search receives
only a fixed weighted graph; it knows nothing about reports, HMMs or responders.
The future allocator will receive feasible responder/incident route candidates.

Input records are frozen dataclasses. Their probability/history dictionaries
should be treated as input data, not mutated simulation state. Keep dynamic
responder positions and availability separately, as the new controller does.

## Units, deadlines and availability

The scenario README explicitly states metres, metres/second and seconds,
including fractional simulation times. Base road time is **distance / speed**;
there is no factor of 3.6 or 3600. Preserve floats in routing; later CP-SAT time
scaling must conservatively round durations up and deadlines down, documenting
the precision and potential exclusion of borderline feasible assignments.

Deadlines are absolute **arrival** times (assignment pp. 2-3). At release 10
with deadline 50, arrival at 50 is allowed. Service can finish later.
Completion = departure + route time + service time. Response time = arrival -
incident release, including dispatch waiting. The simulator validates and
executes explicit assignments under modeled travel durations.

Available responders are initially ready at zero. Busy responders are initially
ready after `time_until_available`; assume their supplied start location is
their position when released, since the files supply no other completion
location. Busy with remaining time zero is permitted as ready at time zero.
Available with a positive remaining time is rejected as inconsistent.

Implemented dispatch is non-preemptive. Occupancy covers [departure, completion),
including travel and service. A responder completing at t may depart at t.
After completion, the responder stays at the incident node. Do not reset them
to the station or reserve them for incidents that are not yet known.

Strict arrival deadlines are a configurable baseline, NOT a requirement to
abandon all late incidents. Work status and deadline result are separate.
strict_deadlines=True rejects predicted-late candidates and closes pending work
after its deadline; False keeps it pending/eligible and permits completed+missed.
A deadline preceding release remains valid-but-infeasible input for strict mode;
late mode can still respond. Missing capabilities remain an input warning.

## Roads and Bayesian uncertainty

Roads are directed. The loader rejects duplicate endpoints, unknown references,
duplicate sources and conflicting known weather for the same road. Reverse-road
evidence is separate. Reports are available at time zero, with local weather.

`bayesian.py` implements Weather -> Status -> three source-report variables.
For each status multiply P(status|weather) by the present source likelihoods,
then normalize. Report CPTs are indexed [true status][reported status]. If weather
is unknown, first marginalize sum_w P(w)P(status|w). Missing reports contribute
one because their likelihoods sum to one over unobserved values. Silence is not
an Open report; missingness is assumed uninformative. All three scenario CPTs
are identical. No road-type/spatial reliability information is invented.

Course references: Bayes' Nets part 1 slides 10-17 (conditional independence and
factorization), part 2 slides 4-6 and 11 (evidence, normalization, enumeration and
variable elimination). Explicit summation/multiplication is exact for this small
network; no general Bayesian engine or sampling is necessary.

Report sources are assumed conditionally independent given status. Copying one
source's report into another can therefore cause overconfidence. Direct products
are suitable for the current at-most-three sources. Zero evidence likelihood,
including extreme numerical underflow, raises a diagnostic rather than a fake
uniform/all-open fallback. Reports are consumed once, not reapplied per dispatch.
Status is held static because the dataset supplies no accessibility dynamics.

Full distributions cover every directed road and inputs are unchanged. No joint
cross-road model or ground-truth state is inferred. Roads with no reports also
lack known weather, so receive the marginalized prior (.685,.180,.135), ordered
Open/Congested/Blocked. Neighbors' and reverse roads' weather is not borrowed.

Worked Scenario1 N1->N2: Rain, Citizen/Police Blocked, Sensor Congested yield
weights (.00012,.00384,.00441). Divide by .00837 for posterior
(.014336917563,.458781362007,.526881720430). Reverse N2->N1 has three Congested
reports and posterior (.005911718339,.993168681030,.000919600631).

The user asked to preserve uncertainty rather than treat the most likely state
as certain. The earlier MAP proposal is superseded. Inference is separate from
the implemented policy in `risk_routing.py`, which requires a threshold tau in
[0,1] and retains only roads with P(Blocked) < tau. Accepted road costs are:

```text
normal_seconds * (P(Open) + 1.5*P(Congested)) / (P(Open) + P(Congested))
```

This is expected EDGE time conditional on that edge being traversable. The sum is
a planning score in seconds, NOT unconditional expected arrival time. With road
dependence it need not equal expected route time conditional on whole-route
success. No finite unconditional Blocked traversal time is supplied; adding an
arbitrary failure penalty would require a separate decision model.

No threshold is prescribed or calibrated as a safety limit. The API and CLI for
Bayesian routing require it explicitly. Example .20 is illustrative, not a default.
Equality excludes the road; zero excludes all edges; one excludes certain
blockages only. Complete distributions remain available even for excluded roads.
`build_graph` remains an all-open or explicitly labelled legacy adapter; new
integration uses `build_bayesian_graph` instead. UCS itself is unchanged.

UCS minimizes this score among accepted edges, not risk. A slower safer route
may be passed over. For distinct used road marginal blockage probabilities p_i,
report dependence-agnostic bounds:

```text
max_i(p_i) <= P(any used road blocked) <= min(1, sum_i(p_i))
```

There is no independent-road product claim. Repeated visits to a directed road
count once under static status; zero-edge routes have bounds (0,0). These bounds
do not estimate lateness or calibration error. A path of accepted roads can
exceed tau in whole-route risk. Route-level chance constraints, failure/recovery
simulation and cross-road dependence models remain alternatives, not implemented.

Scenario1 N1->N2 at tau=.20 takes N1->H1->N2, score 86.7780346821 seconds, blockage
bounds [.135,.27]. Its baseline direct road costs 51.6666666667 seconds with
posterior blockage .5268817204. At tau=.10 the requested route disappears.
Scenario2 at tau=.20 removes N1<->N2 (each blockage .8301957831), leaving 60/132
distinct node pairs reachable. Thresholds are never silently relaxed to recover
connectivity. See TESTING.md for threshold sensitivity and all measured results.


## HMM traffic and historical observations

Traffic hidden state is Low/Medium/High, distinct from road status. It cannot
make a blocked road traversable. The file also uses Low/Medium/High as noisy
observation labels; equal vocabulary does not make an observation the true state.

Future HMM: independently order each directed road's history by `observation_nr`.
Use supplied `initial` as the state distribution for observation 1, apply that
first observation's emission, normalize, then alternate transition and emission
updates for later observations. With row convention T[current][next], prediction
is b*T. `emission[hidden][observed]` gives the likelihood. This follows course
HMM slides 3-4, 9, 17-22 (forward filtering). Viterbi (slides 31-34) answers a
different question: the most likely full state sequence.

No physical sampling interval or historical time origin is supplied. Initial
integration decision: filter once at startup and hold the resulting traffic
belief fixed throughout the simulation; **do not invent one transition per
second**. Treat the final historical belief as a proxy for dispatch-time traffic,
explicitly noting its unknown age. Roads without history use the supplied
initial distribution. This cannot capture live traffic changes.

To give traffic a separate planning role later, adopt transparent **assumed**
travel multipliers Low=1.0, Medium=1.25, High=1.5, with expected multiplier
`sum_x belief[x] * multiplier[x]`. A future integration could multiply this by the
conditional Bayesian edge cost after threshold filtering. This assumes storm
accessibility effects and background traffic contribute separate slowdowns;
they may overlap in reality.
These factors are not prescribed in the files. Compare against all traffic
factors=1 and a stronger congestion setting before claiming benefit. No traffic
multiplier or filtering is applied in the current code.

Do not multiply Bayesian and HMM posteriors: their random variables differ.
Do not count the same report as both models' evidence.

## Handwritten UCS

Search slides 44-47 define expansion by minimum cumulative cost. `search.py`
uses a heap, best-cost map and parent pointers. Accept the goal when popped,
not first discovered; skip superseded queue entries. A strict improvement test
prevents zero-cost cycles. `Route` includes nodes, road IDs and total seconds.
Start=goal returns a zero-cost route; unreachable returns None.

For a finite fixed graph with finite nonnegative weights, this finds a minimum
cost route. The positive minimum edge-cost assumption in the course's infinite
search-tree discussion is stronger than needed for this finite graph. Optimality
is relative to supplied estimates, not unknown true conditions or future events.
Updating costs mid-search is unsupported; build a new snapshot instead.

UCS avoids relying on coordinate geometry. Distances in all supplied scenarios
are at least straight-line distances, so Euclidean distance / maximum speed
could support a later A* lower bound when costs only increase. UCS is sufficient
for the current graphs and remains the reference implementation.

## Next modules, deliberately deferred

The event controller is implemented; the next allocator will consume its frozen
DecisionSnapshot interface. OR-Tools CP-SAT will choose among currently revealed
incidents and free qualified responders: one immediate incident per responder,
one responder per incident, capabilities and reachability. Deadline feasibility
must follow the configured strict/late policy rather than be hardcoded.
Priority policy: lexicographically maximize handled Critical, then High, Medium,
Low; then minimize total response time. This policy avoids the empty-allocation
optimum from minimizing response time alone. It may sacrifice several low-priority
incidents for one critical incident; document that consequence.

An independent plan validator should replay availability, capability, departures,
route adjacency, travel time, deadlines and completion positions. Event ordering
at equal times: process all releases and completions before dispatching. Do not
add dynamic rerouting before representing en-route positions correctly.

Eventually `run.py` must write `plan.json` and `statistics.txt`. It currently
prints Bayesian distributions and an optional route or scripted simulation JSON instead.
Do not submit this checkpoint as the complete assignment. Future statistics: handled count, distinct
responders, mean response time over handled incidents (N/A if none), deadlines met
over all released incidents (unhandled count as not met), plus handled-only
percentage. State the horizon and units. No final plan metrics are claimed here.


## Implemented event controller and scripted tests

`simulation_models.py` defines frozen views/results. `simulation.py:simulate`
owns the event queue and private dynamic state. `scripted.py` supplies explicit
dispatch fixtures; there is no CSP, greedy allocator, future reservation or
automatically optimized dispatch. Caller-provided scripts can have hindsight;
their success tests mechanics, not online allocation quality.

`simulate(scenario, graph, dispatcher, strict_deadlines=True, decision_times=())`
copies the routing graph and accepts a callback returning AssignmentRequest IDs.
The callback receives only current time, immutable responder/revealed-incident
views, current UCS candidates and the deadline-policy flag. It receives no engine,
Scenario or future-release queue. This prevents accidental API lookahead; it is
not a security boundary against a malicious callback independently reading files.

Events use a min-heap keyed by (time, insertion counter). Releases, initially busy
readiness, arrivals and completions at the same float timestamp are drained before
a dispatch decision. Proposals are validated as one batch before any commit:
current availability, released/pending work, capability, route/deadline feasibility
and no repeated responder/incident. Invalid scripts raise errors; they are not
silently repaired or partially committed. Prior processed events are not rolled
back when a callback fails, and an invalid run returns no successful result.

A commitment freezes route, departure, modeled arrival and completion. Responders
are initially_busy, available, travelling or treating. Travelling location is None;
arrival establishes the destination node and begins service. Completion frees the
responder at that node, not its station. Travel plus service occupies [start,end),
so a responder finishing at t can depart again at t. Initially busy jobs have no
invented incident/route; readiness releases them at their supplied start node.
Busy with zero remaining time is processed before zero-time dispatch.

Incident work states are pending, travelling, treating, completed, closed_unassigned.
Deadline outcomes are independently not_due, met, missed. Arrival <= deadline is
met even if service finishes later. Deadline events finalize only after same-time
zero-travel arrivals and zero-service completions settle. Such chains may cause
additional decision rounds at the same timestamp; each incident commits once,
so a finite stream cannot make this loop infinite. An empty decision causes time
to advance, not a repeated no-progress callback loop. A strictly pre-release
deadline is already missed when revealed, without scheduling events in the past.

In strict mode, still-pending missed work closes with strict_deadline_unassigned.
In late mode it remains eligible, including dispatch after the deadline and
completed+missed outcomes. If no events or explicit wake-ups remain, unassigned
late-mode work closes with no_more_events_unassigned; it is never called completed.
No-path/free-capability failures simply produce no current candidate. They do not
prove permanent infeasibility, and later availability can enable a candidate.

The controller processes future releases even when current decisions are empty,
and finishes all travel/service. Obsolete deadlines for already-met work do not
extend the horizon. Initial busy-readiness events and explicit scripted wake-ups
are processed even when otherwise idle; final time is the last relevant event,
not wall-clock runtime. Script wake-ups permit intentionally delayed departures.
Each script timestamp is consumed once, so zero-duration closure cannot replay it.

Float seconds are preserved with no broad equality tolerance. Distinct timestamps
are not merged, avoiding early release of near-future work. Decimal rounding may
still matter near deadlines; displayed rounding never feeds the clock. Finite
overflow and positive durations too small to advance a huge float clock raise
ValueError. A future conservative integer-time representation is an alternative.

Execution uses frozen estimated edge costs as deterministic travel durations.
No ground truth, blockage discovery, failure recovery or forecast-error calibration
is modeled. Results are modeled execution outcomes, not guaranteed arrivals.
Thresholds stay configurable and are never relaxed silently. The CLI also reports
Bayesian blockage bounds for each committed route; these do not simulate failures.

Scenario1 example: R1->I2 and R2->I4 at zero, R4->I1 on initial readiness at 10,
R1->I5 at an explicit wake-up at 120. With Bayesian threshold .20:

| Responder/incident | Departure | Modeled arrival | Modeled completion |
| --- | ---: | ---: | ---: |
| R1/I2 | 0 | 86.778035 | 116.778035 |
| R2/I4 | 0 | 53.067823 | 63.067823 |
| R4/I1 | 10 | 66.968786 | 76.968786 |
| R1/I5 | 120 | 197.347140 | 217.347140 |

All four are completed/met, including I5 whose service finishes after its arrival
deadline 200. I3/I6/I7 close unassigned/missed because the fixture does not request
them. This is not a coverage-optimal plan. At 116.778 R1 is free in N2 but the
script deliberately waits until 120; no dispatcher had to be told about I5 before
its release at 50. See TESTING.md for an independent replay of these commitments.
