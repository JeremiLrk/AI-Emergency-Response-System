# Design decisions and boundaries

This checkpoint implements loading/validation, exact Bayesian road inference,
probability-aware graph construction, route blockage bounds, handwritten UCS and
event simulation, online OR-Tools CP-SAT allocation, nearest-feasible comparison
and modeled statistics, historical HMM Forward filtering and independent traffic
route preferences, required plan/statistics export and independent plan replay.

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
The allocator receives only current feasible responder/incident route candidates.

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

Implemented HMM: independently order each directed road's history by `observation_nr`.
Use supplied `initial` as the state distribution for observation 1, apply that
first observation's emission, normalize, then alternate transition and emission
updates for later observations. With row convention T[current][next], prediction
is b*T. `emission[hidden][observed]` gives the likelihood. This follows course
HMM slides 3-4, 9, 17-23 (Forward filtering). Viterbi (slides 31-34) answers a
different question: the most likely full state sequence.

No physical sampling interval or historical time origin is supplied. Initial
integration decision: filter once at startup and hold the resulting traffic
belief fixed throughout the simulation; **do not invent one transition per
second**. Treat the final historical belief as a proxy for dispatch-time traffic,
explicitly noting its unknown age. Roads without history use the supplied
initial distribution. This cannot capture live traffic changes.

Earlier multiplier/maximum proposals were rejected: they can give an Open road
more than normal travel time and double-count congestion. Bayesian road conditions
alone retain responsibility for time: normal for Open, 1.5 times normal for
Congested, unusable for Blocked. The existing posterior-conditional edge estimate
and configurable blockage threshold are unchanged.

Do not multiply Bayesian and HMM posteriors: their random variables differ.
Do not count the same report as both models' evidence.

### Forward equations and actual worked example

Let pi(x)=P(X1=x), T[y][x]=P(Xk=x|X(k-1)=y), E[x][e]=P(ek=e|Xk=x).
For the first historical observation, w1(x)=pi(x)E[x][e1] and
b1(x)=w1(x)/sum_z w1(z). For k>1:

    prediction_k(x) = sum_y b_(k-1)(y) T[y][x]
    w_k(x) = prediction_k(x) E[x][e_k]
    b_k(x) = w_k(x) / sum_z w_k(z)

This sums hidden paths, rather than taking Viterbi maxima. Normalization each step
avoids multiplying a long sequence of tiny likelihoods. Impossible evidence raises
an error; it does not create a uniform distribution. Supplied positive tables do
not have this problem. Interpreting initial as P(X1), rather than P(X0), is an
explicit indexing choice consistent with the course's X1/E1 base case; the slide
umbrella example also illustrates a different X0 indexing, so do not mix them.

Scenario2 uses pi=(.50,.35,.15), unlike Scenarios1/3 (.60,.30,.10).
Its transition and emission rows, in Low/Medium/High order, are:

| Hidden/current state | T to Low, Medium, High | E observed Low, Medium, High |
| --- | --- | --- |
| Low | .75, .22, .03 | .80, .18, .02 |
| Medium | .15, .70, .15 | .15, .70, .15 |
| High | .03, .22, .75 | .02, .18, .80 |

H2->N8 has observations Low, Medium, High, Medium, High. First weights are
(.4000,.0525,.0030), sum .4555, giving b1 below. Step2 prediction is
(.676103183315,.275323819978,.048572996707); emission reweighting yields
(.121698572997,.192726673985,.008743139407), sum .323168386389.

| Prefix length | P(Low) | P(Medium) | P(High) |
| ---: | ---: | ---: | ---: |
| 1 | .878155872667 | .115257958288 | .006586169045 |
| 2 | .376579449360 | .596366111606 | .027054439034 |
| 3 | .041359105118 | .421348676462 | .537292218420 |
| 4 | .049706783670 | .739730632892 | .210562583438 |
| 5 | .010113305926 | .282220273412 | .707666420662 |

N8->H2 has no history and retains (.50,.35,.15); it never borrows reverse evidence.
All three states and observation counts/prior provenance remain available.
There are 14/14, 3/30 and 10/60 observed directed roads in Scenarios1/2/3,
respectively (140, 15, 100 observations). Prior-only roads are uncertain, not
known low-traffic. No stationary-distribution fallback or extra prediction across
an unknown historical-to-simulation time gap is assumed.

### Independent routing preference

Define Q(path)=sum_e normal_seconds(e)*P_HMM(High_e|history). Normal seconds
weight historical exposure by the reference traversal duration. Q is a score,
not expected present travel time, a road-failure probability, or evidence that a
route is safe. It is additive without assuming independent road states; each
traversal contributes, even when an edge repeats. Medium remains in the full
distribution but the chosen preference uses High only. These are project policy
choices, not formulas mandated by the assignment/slides. No Bayesian/HMM joint
distribution or independence between congestion concepts is asserted.

Three selectable policies:

1. bayesian-only: original handwritten scalar UCS on unchanged Bayesian seconds.
2. hmm-tie: handwritten lexicographic UCS minimizing (T,Q). Time equality is
   exact, not an epsilon or rounded comparison. Queue entries carry both values.
3. hmm-bounded: first find the tie-optimal shortest route with T*,Q*. Search for
   min (Q,T) subject to T <= (1+epsilon)T*. Accept it only if Q<Q* and
   Q <= (1-eta)Q*. Otherwise use the tie-optimal shortest route. Q*=0 and T*=0
   never induce detours. epsilon=0 reduces to the exact tie policy. Fractions
   must be finite in [0,1]; CLI requires an explicit bounded allowance.

For evaluation epsilon=.05 and eta=.10 were declared BEFORE seeing results.
The same settings apply to all scenarios, responders and deadline policies.
No weights were fitted to improve coverage. Configurability enables later
predeclared sensitivity experiments, not retrospective best-result selection.

The bounded problem needs Pareto labels (time,Q) per node. A label can be dropped
only when another has no greater time AND no greater exposure. One scalar best
value per node is insufficient. A priority queue ordered by (Q,T) returns the
best feasible goal; nonnegative costs and dominance suppress redundant cycles.
This resource-constrained extension is our own search design, beyond ordinary
course UCS. It can require exponentially many labels; a configurable 100000-label
guard raises TrafficSearchLimit visibly, never silently approximates an optimum.

The simulator accepts an optional route planner receiving only the graph,
current endpoints and, in strict mode, the remaining arrival-duration budget.
That budget further caps a detour; a feasible shortest response is not discarded
because a preferred detour is too late. The absolute arrival test remains final,
including a shortest-route fallback for floating subtraction boundary rounding.
Planner route shape, directed edges and the exact sum of original edge seconds
are rechecked. Route.seconds is always T. Arrival=now+T and completion=arrival+
treatment drive deadlines, location and availability. The exposure score never
enters those calculations or the CP-SAT response objective.

Allow-late mode has no hard deadline route cap. A bounded detour can change an
otherwise on-time pair into a late pair; CP-SAT sees the resulting on_time flag,
but is offered only one route per pair. We do not jointly optimize route options
and allocation. Committed routes remain fixed; no online HMM events/rerouting.
A lower exposure route can also have a larger Bayesian blockage bound: the
threshold still filters edges, but neither policy enforces route-level safety.

See TESTING.md and results/traffic_comparison.json: exact ties change nothing in
these scenarios; bounded routing changes seven all-pairs routes in Scenario3,
but none of the actual commitments. This absence of dispatch benefit is retained.

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

## Remaining modules

All four AI components, event execution, required plan.json/statistics.txt export
and independent standalone plan validation are implemented. Real road-failure/
recovery execution and calibration remain limitations rather than new mandatory
features. The final report.pdf, repository submission/access requirements and oral
defence preparation still need completion. Tests do not establish calibrated
uncertainty or an optimal full-horizon response plan.

## Implemented event controller and scripted tests

`simulation_models.py` defines frozen views/results. `simulation.py:simulate`
owns the event queue and private dynamic state. `scripted.py` supplies explicit
dispatch fixtures. The separate allocation.py and baseline.py callbacks now
provide automatic decisions without adding optimization inside the controller.
Future reservations and multi-job scheduling are still absent. Caller-provided scripts can have hindsight;
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


## Implemented CP-SAT allocation after objective review

The user accepted Boolean variables and compatibility constraints but rejected
deadline ranking before response minimization. No EDF/slack/rank/aging term is
implemented. A fresh model consumes only DecisionSnapshot; it does not load files,
hold Scenario or inspect future events. Existing candidate generation enforces
release, availability, capability, routing and selected strict/late policy.
The allocator defensively checks candidate/snapshot consistency again, and the
simulator independently validates the returned batch.

For every eligible pair, x[r,i] is Boolean. For each pending incident y[i] is
Boolean and equals sum_r x[r,i], hence also enforces at most one responder.
For every responder sum_i x[r,i] <= 1. Missing pairs have no variable; incidents
without candidates have y=0. Leaving work unassigned is allowed, so all-zero is
feasible. INFEASIBLE is a model error rather than proof that some emergencies
cannot be served. These Boolean sum constraints follow the course CSP slides 2
(variables/domains/constraints), 9 (general solver) and 10 (CP-SAT Boolean matrix).

Approved lexicographic objective:

1. Maximize assigned Critical, then High, then Medium, then Low counts.
2. In allow-late mode only, maximize on-time assignments in that same priority
   order, while preserving every earlier coverage optimum.
3. Minimize summed predicted response time arrival-release, including waiting.

Coverage dominates time, so the empty assignment cannot win merely because its
response sum is zero. Late Critical coverage still precedes High on-time coverage;
the policy may not maximize overall on-time percentage. On-time means modeled
arrival <= deadline; treatment may finish later. There is no treatment-duration,
scarce-capability-preservation or route-risk objective. Those can affect later
outcomes but must not be added silently.

Each level uses an ordinary CP-SAT linear objective. Only a proven OPTIMAL value
is fixed as an equality before proceeding. Constant-zero priority levels are
skipped. Response coefficients are ceil(1000*(arrival-release)) integers. This
quantizes only the objective, not simulator times/deadline eligibility; a proven
integer optimum is not an exact continuous-time optimum. Safe integer range is
checked. Priorities/counts are integers, so no floating hard constraints are added.

No arbitrary priority benefit/time penalty or big-M coefficient is used. Solves
share one configurable wall budget per snapshot, default 2 seconds, including
elapsed model-building time when computing remaining time. Model construction
and Python overhead cannot be preempted, so this is not a hard process wall-time
guarantee. Solver workers=1 and seed=0; variables/constraints use stable input order.
Exact ties may still differ across solver versions/platforms. No extra tie-breaking
objective, future-capability heuristic or hindsight is introduced.

Status handling:

* OPTIMAL: retain incumbent, fix this objective, continue.
* FEASIBLE: retain valid solution, stop hierarchy; do not freeze an unproven optimum.
* UNKNOWN or exhausted remaining budget: retain the previous valid incumbent,
  otherwise return no requests. Diagnostics explicitly distinguish no incumbent
  from NO_CANDIDATES. Empty fallback may delay work until the next event; no
  unapproved greedy fallback or silent budget reset occurs.
* MODEL_INVALID/INFEASIBLE/unexpected status: raise AllocationError, abort visibly.
* NO_CANDIDATES: trivially optimal empty decision, without solving.

Diagnostics record phase statuses, exact achieved integer values, solver bounds,
solver wall time, returned count and whether the whole hierarchy was proven.
Simulator time does not advance by solver wall time: computation is assumed
instantaneous in modeled execution, a further realism limitation.

## Baseline and comparison interpretation

NearestDispatcher sorts eligible pairs by shortest travel, then responder/incident
ID and greedily accepts nonconflicting pairs. It ignores priority, waiting age and
on-time preference in late mode. It is deliberately simple and may waste a flexible
responder; CP-SAT optimizes the complete current batch. Both receive identical
snapshot eligibility, road threshold, estimates and strict/late policy. This is
an ALLOCATION baseline, distinct from routing-policy baseline (all-open roads).

benchmark.py compares both on all three supplied scenarios, strict and allow-late,
with fresh state each time and Bayesian threshold .20. Configuration and full
commitments are in results/allocation_comparison.json. Python 3.12.14 and OR-Tools
9.15.6755 were tested. Repeating the comparison reproduced JSON metrics and
commitments under this configuration; no sampled hidden road truth is involved.

Statistics: handled means completed treatment, including late responses. Deadline
met count is independent; all-incident percentage counts unhandled as not met.
Also report handled-only percentage. Average response is arrival-release over
completed incidents only; no completed incidents means None/N/A, not zero. This
average must be interpreted with coverage because different policies handle
different incident subsets. Counts by priority are also reported.

Unexpected but valid result: Scenario3 strict CP-SAT handles 13/20 versus nearest
15/20, despite all local objective levels being proven optimal. In the recorded
initial tie for First-aid I4, CP-SAT selects R2 while nearest selects R1 at the same
cost. R1 has Medical emergency capability; R2 does not. Different later positions
affect I11 and I14. In this run the nearest policy happens to place a suitable unit
for those future calls. This is no proof of global superiority for either policy:
no allocator may use future incidents, and the immediate objective ignores later
location/capability value. See TESTING.md for all measured comparisons.

## Assignment-format output and independent validation

Requirements were checked before implementation against Assignment1 (1).pdf,
sections3.1-3.3,5.1,5.2 and8.2, and Scenarios/README.md. Section5.1 specifies an
exact top-level list, not a custom object containing events/statistics:

```json
[
  {"responder_id": "R1", "incident_id": "I1", "path": ["N1", "H1", "N2"], "time": 0}
]
```

The example is illustrative, not claimed feasible for a particular supplied
scenario. time is absolute assignment START/departure time, not release, arrival,
completion or solver wall time. path is the full ordered node sequence; directed
road keys follow adjacent nodes. A responder already at the incident has a
singleton path. Unhandled incidents have no plan row; multiple incidents handled
by one responder appear as separate rows at their recorded start times. Fractional
seconds are retained, as required by Scenarios/README.md. No arrival/duration,
traffic score, metadata wrapper or extra assignment keys are added to plan.json.

Section5.2 requires handled incidents, responders used, average response time and
deadline percentage; its sample text layout is illustrative. It explicitly asks
us to explain calculations and unhandled incidents. Existing statistics are used:

- handled = completed treatment, including permitted late responses;
- responders used = distinct responders in committed assignments;
- response = arrival minus incident timestamp, including dispatch waiting/travel,
  excluding treatment; mean over handled incidents only, N/A when none handled;
- primary deadline percentage = on-time arrivals divided by ALL input incidents;
  unhandled count as not met. Empty input gives N/A, not an invented100%;
- handled-only percentage, unhandled/late counts and unhandled IDs add context.

statistics.txt starts with the four expected metrics and includes units,
denominators, assumptions, policy-relative validity, assigned-arrival deadline
compliance and run configuration. It retains float precision rather than rounding
start times or feasibility checks. Low average response alone is not good coverage.

### Export boundary

outputs.make_plan projects SimulationResult.assignments directly:
responder_id,incident_id,route.nodes,departure_time. It performs no allocation,
routing or scheduling. outputs.write_outputs uses summarize(result) for exported
statistics and invokes original-data validation before writing. Replayed travel,
arrival and completion must equal every recorded assignment; independently
recomputed statistics must equal summarize(result). Invalid/mismatched results
raise before output creation. This extra calculation belongs to validation, not
a second simulation or another source of exported timing decisions.

run.py normal CSP, nearest and script executions write plan.json/statistics.txt
to the current working directory by default, or --output-dir DIR. No output
location is specified in the assignment, so this is our explicit convention.
Repeated runs replace the same filenames; separate directories preserve scenarios.
--compare writes DIR/csp and DIR/nearest to prevent the two plans overwriting each
other. Diagnostic --route performs no assignment run and writes neither artifact;
it rejects a nondefault --output-dir. stdout remains diagnostic JSON, with output
paths/validation added. Required plan files retain the exact assignment schema.
Writing two separate files is not a filesystem transaction; I/O errors propagate.

Existing defaults (optimistic all-open graph, original UCS) are retained rather
than changing model policy during this task. README's full-system command opts
explicitly into Bayesian routing and HMM; the original baseline remains useful.
Settings are recorded in statistics.txt because the required plan format has no
configuration fields. The validator must be given the same routing policy and
threshold. It never guesses them from paths or silently selects a safer policy.

### Independent original-data replay

plan_validation.validate_plan receives the original validated Scenario plus a
decoded plan, routing assumptions and deadline policy. It does not consume the
simulation result/graph/events/candidates, call simulate/UCS/CP-SAT, or trust any
claimed timing in a plan. It reuses Bayesian probability inference (already tested)
and the Statistics data container, but independently rebuilds directed road lookup,
blockage filtering, edge costs, responder timelines and summary calculations.
It does not reuse build_bayesian_graph, the simulator time helper or summarize.

Validation checks:

1. Exact list/row schema, known string IDs/nodes and finite nonnegative start times
   (booleans/NaN/Infinity rejected). The JSON reader also rejects duplicate keys.
2. Each incident assigned at most once, even by different responders. Unhandled
   incidents are permitted and reported; responder reuse is permitted over time.
3. Required capability is explicitly in that responder's input capabilities.
4. Start >= incident release and >= initial readiness/previous completion.
5. Path starts at current responder location and ends at the incident. Every
   adjacent pair is an ORIGINAL directed road; no implicit reverse arcs.
6. Under Bayesian policy, each edge passes the supplied threshold; duration is
   independently computed from distance/speed and posterior-conditional1.5 rule.
   Baseline uses normal time explicitly, not a guarantee that roads are Open.
7. Arrival = start + summed travel; completion = arrival + original treatment.
   Both must be finite/representable. The responder remains occupied until
   completion, then remains at the incident for the next job.
8. Arrival <= absolute deadline in strict mode; equality is allowed and treatment
   may finish later. Late mode produces warnings/outcomes without hiding lateness.

Rows are replayed by (start time,original row index); arbitrary list ordering is
accepted. Original order resolves same-time zero-duration sequences. Finishing
treatment exactly at the next start is legal. Initially busy units become ready
at their supplied start location because no initial external job destination is
provided. Invalid plans return diagnostic row indices/codes and no performance
statistics, avoiding misleading scores for invalid assignments.

validate_plan.py is a separate read-only entry point; exit0 means policy-valid,
exit1 invalid plan, exit2 malformed file/configuration. It requires no OR-Tools.
The exact schema has no arrival/treatment fields to falsify; they are reconstructed
from original inputs. During export, those values are cross-checked against the
simulation's richer assignment records to detect timing bugs.

### Validity, deadlines and performance are different claims

An empty plan can be operationally valid and handle no incidents. A valid plan
need not choose shortest routes, optimal priorities or the best responder. The
validator intentionally checks feasibility, not whether a solver/model performed
well. deadline_compliant means all ASSIGNED arrivals meet their deadlines and
the plan has no errors; it does not mean every incident was served. Coverage and
the all-incident deadline denominator separately expose omitted work.

With --allow-late, valid means feasible under that explicitly relaxed experimental
policy; late assignments do NOT satisfy the assignment's strict arrival-deadline
rule. statistics.txt labels this distinction. Strict remains default for submission
examples. Lower historical exposure does not establish lower blockage risk.

Validity is conditional on the selected estimates and threshold, not unknown
actual road states/arrivals. Shared Bayesian inference can have shared errors;
independent replay is not fully independent probability verification. Final plans
can prove no early dispatch, but cannot establish that an allocator never used
future information when choosing among otherwise feasible assignments; snapshot
boundary tests address that separately. No real-road safety, global optimum or
perfect traffic calibration is certified.

See TESTING.md and results/plan_export_validation.json for six actual CLI exports
and standalone replays (three scenarios, strict/late), plus adversarial tests.
Earlier poor Scenario3 coverage and unchanged HMM outcomes are preserved.
