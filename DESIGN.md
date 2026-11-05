# Design decisions and boundaries

This checkpoint implements input loading, validation, graph snapshots and UCS.
It does not implement Bayesian inference, HMM inference, OR-Tools allocation,
simulation, or final dispatch output. The architecture below specifies their
intended contracts without adding unused placeholder modules.

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

`load_scenario` -> typed `Scenario` -> routing snapshot -> `ucs` -> `Route`.

The loader may parse future incidents, but a future controller must call
`scenario.known_incidents(now)` and plan only with those records. Search receives
only a fixed weighted graph; it knows nothing about reports, HMMs or responders.
The future allocator will receive feasible responder/incident route candidates.

Input records are frozen dataclasses. Their probability/history dictionaries
should be treated as input data, not mutated simulation state. Keep dynamic
responder positions and availability separately when simulation is implemented.

## Units, deadlines and availability

The scenario README explicitly states metres, metres/second and seconds,
including fractional simulation times. Base road time is **distance / speed**;
there is no factor of 3.6 or 3600. Preserve floats in routing; later CP-SAT time
scaling must conservatively round durations up and deadlines down, documenting
the precision and potential exclusion of borderline feasible assignments.

Deadlines are absolute **arrival** times (assignment pp. 2-3). At release 10
with deadline 50, arrival at 50 is allowed. Service can finish later.
Completion = departure + route time + service time. Response time = arrival -
incident release, including dispatch waiting. The code preserves these input
fields, but does not yet schedule or validate assignments.

Available responders are initially ready at zero. Busy responders are initially
ready after `time_until_available`; assume their supplied start location is
their position when released, since the files supply no other completion
location. Busy with remaining time zero is permitted as ready at time zero.
Available with a positive remaining time is rejected as inconsistent.

Later dispatch is non-preemptive. Occupancy covers [departure, completion),
including travel and service. A responder completing at t may depart at t.
After completion, the responder stays at the incident node. Do not reset them
to the station or reserve them for incidents that are not yet known.

Use hard arrival constraints on estimated travel time. Keep infeasible incidents
explicitly unassigned rather than breaking a constraint. A deadline preceding
release is a feasibility warning, not a malformed file. So is an incident with
no suitably qualified responder. Pending incidents may wait for a completion
event until their deadline is no longer achievable.

## Roads and Bayesian uncertainty

Roads are **directed**. Every supplied graph happens to list reverse edges,
but reverse evidence can differ. Never add reverse edges or share beliefs
implicitly. `(from, to)` uniquely identifies each supplied road. Because there
are no input road IDs, the adapter rejects duplicate endpoint pairs instead of
silently overwriting parallel roads. The generic graph still supports parallel
edges, preserving their IDs in routes.

Road reports are all known at t=0. Weather is local to the directed road.
For a road with reports, use its known weather; do not infer one global Storm
value. The loader rejects conflicting weather or duplicate source reports on
the same directed road: the supplied schema has no report IDs/timestamps to
disambiguate duplicates or changing weather.

Future Bayesian model: Weather -> Status -> three source-specific report
variables. Use `P(status | weather) * product P(report | status)` and normalize,
under the documented assumption that report sources are conditionally
independent given status. The CPTs support this model, but do not establish
that real reports are independent. Correlated reporting may cause overconfidence.
Use only sources actually present. If the likelihood normalizer is zero, stop
with a diagnostic; do not fabricate a posterior.

For roads with no reports, weather is also missing. Future inference should
marginalize `sum_w P(status | w) P(w)`. This is why `weather_prior` must remain
available even though weather is known on reported roads. Reverse-road weather
is not borrowed silently.

Initial integration policy: select the maximum-posterior road status, breaking
ties conservatively Blocked > Congested > Open. Remove Blocked edges; apply
1.5 exactly for Congested; Open uses normal time. Retain posteriors for explanation.
This simple MAP approximation may exclude usable roads or select blocked roads.
It is a design choice, not a probabilistic safety guarantee. Compare it later
with an explicit blocking-probability threshold policy before adding complexity.

Currently `build_graph(scenario)` is explicitly an **all-open, normal-speed
baseline**, not inferred conditions. `build_graph(scenario, statuses)` accepts a
complete caller-supplied status snapshot and applies the specified road effects.
Passing noisy reports directly as truth is not part of the implementation.

Blocked travel has no finite unconditional expectation without a failure/recovery
model. Do not substitute zero, silently discard blockage probability, or claim
that a risk score is a travel-time estimate. No true-state files are supplied;
only feasibility under modeled costs can be checked from these datasets.

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
`sum_x belief[x] * multiplier[x]`. Combine multiplicatively with the MAP road
factor, after checking Blocked. This assumes storm accessibility effects and
background traffic contribute separate slowdowns; they may overlap in reality.
These factors are not prescribed in the files. Compare against all traffic
factors=1 and a stronger congestion setting before claiming benefit. No traffic
multiplier or filtering is applied in the current baseline code.

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

Use a small online event controller at releases and responder completions.
OR-Tools CP-SAT variables will choose assignments only for currently known
incidents and free qualified responders. Constraints: one responder per incident,
one immediate incident per responder, reachability and arrival deadline.
Priority policy: lexicographically maximize handled Critical, then High, Medium,
Low; then minimize total response time. This policy avoids the empty-allocation
optimum from minimizing response time alone. It may sacrifice several low-priority
incidents for one critical incident; document that consequence.

An independent plan validator should replay availability, capability, departures,
route adjacency, travel time, deadlines and completion positions. Event ordering
at equal times: process all releases and completions before dispatching. Do not
add dynamic rerouting before representing en-route positions correctly.

Eventually `run.py` must write `plan.json` and `statistics.txt`. It currently
prints a data summary and optional baseline route instead. Do not submit this
checkpoint as the complete assignment. Future statistics: handled count, distinct
responders, mean response time over handled incidents (N/A if none), deadlines met
over all released incidents (unhandled count as not met), plus handled-only
percentage. State the horizon and units. No final plan metrics are claimed here.
