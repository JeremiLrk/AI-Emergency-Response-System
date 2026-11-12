
# System design

This document describes the architecture, algorithms, planning rules and assumptions of the Emergency Response System.

[CODE_GUIDE.md](CODE_GUIDE.md) explains where these components are implemented. [TESTING.md](TESTING.md) documents the tests and experimental results. [LLM_NOTES.md](LLM_NOTES.md) describes the development process and collaboration with the LLM.

## The normal run in one minute

| Question | Current behaviour |
| --- | --- |
| Which roads can be used? | Roads with less than 20% estimated blockage probability. |
| What determines travel time? | Bayesian Open/Congested probabilities, assuming the road is passable. |
| What does the HMM change? | Route preference. It does not add another slowdown to travel time. |
| How are incidents prioritized? | Critical, then High, Medium and Low, before minimizing response time. |
| Can responders arrive late? | Not in the default menu run. The separate allow-late option permits late arrivals. |
| What happens after treatment? | The responder becomes available at the incident location. |
| Does the allocator know future calls? | No. Incidents are only available to the allocator after their release. |
| Are arrivals guaranteed? | No. The simulation uses estimated travel times and does not simulate actual road failures. |

## System architecture

The system consists of four main AI components:

1. Bayesian reasoning estimates the probabilities of Open, Congested and Blocked road conditions.
2. A Hidden Markov Model estimates historical Low, Medium and High traffic probabilities.
3. Search finds routes using the road estimates and traffic preferences.
4. CP-SAT chooses which available responders should handle the currently known incidents.

An event-based simulator connects these components. It maintains the current time, responder locations, responder availability and incident status.

The main execution flow is:

```text
Load and validate scenario files
              |
              v
Calculate Bayesian road probabilities
              |
              v
Build the road graph
              |
              v
Process historical traffic with the HMM
              |
              v
Start the event-based simulation
              |
              v
Find routes for eligible responder-incident pairs
              |
              v
Choose assignments with CP-SAT
              |
              v
Simulate travel and treatment
              |
              v
Repeat when the situation changes
              |
              v
Validate the completed plan
              |
              v
Write plan.json and statistics.txt
```

The Bayesian and HMM calculations take place before the simulation starts. Routing and allocation are repeated as incidents appear or responders become available.

The allocator receives a snapshot of the current situation rather than the complete future incident stream.

The course methods provide the probability calculations, search algorithms and constraint formulation. Settings such as the blockage cutoff and the traffic-detour allowance are project-specific planning policies rather than requirements of those algorithms.

---

## 1. Units, deadlines and responder availability

### Units

Distances and coordinates are measured in metres, speeds in metres per second, and simulation times in seconds.

The normal travel time of a road is:

```text
normal_seconds = distance / speed
```

No conversion factor such as 3.6 or 3600 is required.

Fractional seconds are preserved in routing and simulation.

### Incident timing

An incident has a release time, an absolute arrival deadline and a treatment duration.

A call released at time 10 with a deadline of 50 must be reached by time 50, not by time 60.

The relevant times are calculated as follows:

```text
arrival = departure + travel_time

completion = arrival + treatment_time

response_time = arrival - release_time
```

The deadline applies to arrival. Treatment may finish after the deadline without making an on-time arrival late.

Response time includes both waiting before dispatch and travel. It does not include treatment duration.

### Responder availability

A responder remains occupied from departure until treatment finishes.

Once treatment is completed, the responder becomes available at the incident location. Their next route starts from that location.

A new assignment may begin exactly when the previous treatment finishes.

The current model does not include:

- Patient transport to a hospital after treatment.
- Hospital handover time.
- Automatic return journeys to stations.
- Interruption or replacement of committed assignments.
- Rerouting during a committed journey.

An initially Busy responder becomes available after `time_until_available`, at the supplied start location.

This location is a modeling assumption because the scenario files do not provide a different destination for the initial job.

Busy responders with zero remaining busy time are allowed. Responders marked Available with a positive remaining busy time are rejected.

### Deadline policies

Two deadline policies are available.

| Policy | Behaviour |
| --- | --- |
| Strict deadlines | Reject assignments whose estimated arrival is after the deadline. |
| Allow late | Permit assignments after the deadline and record the missed deadline separately. |

Strict deadlines are used by the normal scenario menu.

In strict mode, pending incidents are closed when their deadline has passed without an assignment.

In allow-late mode, a call can receive completed treatment while still counting as a missed deadline.

An incident with a deadline before its release time produces an input warning rather than having its deadline silently changed. Such an incident cannot be reached on time in strict mode.

---

## 2. Bayesian road conditions

### Bayesian Network structure

The Bayesian model estimates the condition of each directed road using weather and reports from citizens, police and sensors.

The network has the following structure:

```text
Weather
   |
   v
Road condition
   |
   +--> Citizen report
   +--> Police report
   +--> Sensor report
```

The possible road conditions are:

- Open
- Congested
- Blocked

Each report source has a conditional probability table describing how likely it is to report a particular condition given the actual road condition.

The model assumes that reports are conditionally independent once the true road condition is known.

This assumption allows the likelihoods of the reports to be multiplied.

If report sources copy information from each other, the model may count related evidence more than once and become too confident.

### Probability calculation

For a possible road condition `s`, known weather `w` and available reports, the calculation is:

```text
weight(s) =
    P(s | w)
    * product of P(report | s)
```

The posterior probability is obtained by normalization:

```text
P(s | weather, reports) =
    weight(s) / sum of all road-condition weights
```

This gives three probabilities that sum to one.

When weather is unknown, the weather variable is summed out:

```text
P(s) = sum over w of P(w) * P(s | w)
```

A missing report contributes no additional likelihood factor.

This assumes that the absence of a report is not itself evidence about the road condition.

For a road with neither known weather nor reports, the supplied Bayesian tables give:

```text
Open:       0.685
Congested:  0.180
Blocked:    0.135
```

All three scenarios use the same Bayesian probability tables.

### Directed road evidence

Weather and reports belong to a specific directed road.

Evidence for A -> B is not automatically used for B -> A or for neighbouring roads.

Each road direction is estimated separately.

The reports are available before the simulation and are applied once. Road-condition probabilities remain fixed during the run because the supplied data does not include a road-state transition model or live reports.

The report tables are interpreted as:

```text
table[true_status][reported_status]
```

They are not interpreted in the opposite direction.

Duplicate report sources for one road and conflicting weather values are rejected.

Evidence with zero likelihood raises an error instead of attempting to normalize by zero.

Direct multiplication is sufficient for the three supplied report sources. Larger probability models could require additional numerical techniques to prevent underflow.

### Worked Bayesian example

For road N1 -> N2 in Scenario 1:

- Weather is Rain.
- Citizen reports Blocked.
- Police reports Blocked.
- Sensor reports Congested.

The resulting weights are:

| Road condition | Weight |
| --- | ---: |
| Open | 0.00012 |
| Congested | 0.00384 |
| Blocked | 0.00441 |

Their sum is:

```text
0.00837
```

After normalization:

| Road condition | Posterior probability |
| --- | ---: |
| Open | 0.014336917563 |
| Congested | 0.458781362007 |
| Blocked | 0.526881720430 |

The reverse road has three Congested reports and produces:

```text
Open:       0.005911718339
Congested:  0.993168681030
Blocked:    0.000919600631
```

The example demonstrates why road directions and their evidence must remain separate.

### Retaining uncertainty

The Bayesian component retains the complete probability distribution.

It does not select only the most likely condition using a Maximum A Posteriori (MAP) decision.

For example, a road with a blockage probability of approximately 52.7% is most likely Blocked, but its actual condition remains uncertain.

Retaining all probabilities allows the routing policy to account for that uncertainty separately from the inference calculation.

### Road-use policy

The routing policy accepts a road only when:

```text
P(Blocked) < blocked_threshold
```

A road with a blockage probability exactly equal to the threshold is excluded.

The threshold must be between zero and one.

- A threshold of zero excludes every road.
- A threshold of one excludes only roads that are certainly blocked.
- Lower thresholds generally reduce the available road network.

The normal menu and the main comparisons use:

```text
blocked_threshold = 0.20
```

The same cutoff applies to all incident priorities.

Explicit Bayesian routing commands require the threshold to be supplied.

The 20% cutoff is an experimental planning setting. The assignment does not provide a calibrated probability threshold that guarantees safe emergency travel.

### Estimated travel time

The assignment defines the following travel rules:

| Road condition | Travel behaviour |
| --- | --- |
| Open | Normal travel time. |
| Congested | 1.5 times normal travel time. |
| Blocked | Cannot be traversed. |

For an accepted road, the estimated travel time is calculated conditional on the road being passable:

```text
estimated_seconds =
    normal_seconds
    * (P(Open) + 1.5 * P(Congested))
    / (P(Open) + P(Congested))
```

The denominator normalizes the probabilities over the two passable conditions.

The resulting value is the expected traversal time for that edge, assuming it is not blocked.

The planner adds the estimated travel times of the edges along a route.

No traversal duration is invented for a Blocked road. The travel estimate also does not include an arbitrary blockage-risk penalty.

The estimate is not an unconditional expected travel time that includes possible blockage, recovery or rerouting.

If road conditions are dependent, the sum of the edge estimates can also differ from the expected travel time conditional on the entire route being passable.

### Whole-route blockage risk

A cutoff applied to individual roads does not guarantee that the complete route has the same maximum blockage probability.

For distinct directed roads with blockage probabilities `p_i`, the following bounds are reported:

```text
lower_bound = max(p_i)

upper_bound = min(1, sum(p_i))
```

These bounds follow from the probability of encountering at least one blocked road:

```text
max(p_i)
    <= P(at least one road is blocked)
    <= min(1, sum(p_i))
```

The bounds do not require road failures to be independent.

For example, two roads that each have a blockage probability of 0.15 can together have a route blockage probability greater than 0.20.

A repeated traversal of the same directed road counts once for blockage-risk bounds because road conditions are treated as fixed.

A route with no edges has bounds `(0, 0)`.

The bounds are separate from travel-time estimates and HMM traffic exposure.

A route with lower historical traffic exposure can still have higher blockage-risk bounds.

The current planner minimizes estimated travel time and applies the selected traffic preference. It does not guarantee the safest complete route.

### Effect of the cutoff on actual scenarios

In Scenario 1, a cutoff of 0.20 produces the route:

```text
N1 -> H1 -> N2
```

Its estimated travel time is:

```text
86.7780346821 seconds
```

Its route blockage-risk bounds are:

```text
[0.135, 0.27]
```

The direct road N1 -> N2 has a blockage probability of approximately 0.5268817204 and is therefore excluded.

At a cutoff of 0.10, the requested route becomes unavailable.

In Scenario 2, the 0.20 cutoff removes the roads N1 -> N2 and N2 -> N1. Under this cutoff, 60 of the 132 ordered pairs of distinct nodes remain reachable.

The planner does not automatically relax the cutoff when a route is unavailable.

---

## 3. Hidden Markov Model and historical traffic

### Traffic states and observations

The HMM describes three hidden traffic states:

- Low
- Medium
- High

The observations use the same three labels.

An observation is evidence about the hidden traffic state. It is not assumed to reveal that state with certainty.

These traffic states are separate from the Bayesian road conditions Open, Congested and Blocked.

A road's HMM probability of High traffic is not its probability of being Blocked.

### Historical observation timing

The `observation_nr` field indicates the order of readings for a directed road.

It does not represent simulation time.

The supplied files do not specify:

- The physical time between historical observations.
- The age of the final observation.
- The time between the historical sequence and the start of the simulation.

The complete history of each directed road is processed before dispatch begins.

The final filtered distribution remains fixed during the simulation.

The implementation does not create live traffic events, apply one transition per simulation second or predict across an unknown time gap.

Roads without observations retain the initial distribution supplied for their scenario.

### Forward filtering

The implementation uses Forward filtering to estimate the probability of the final hidden traffic state given the available history.

The initial distribution is interpreted as the state distribution at the first observation:

```text
P(X_1)
```

The first observation is applied directly to this distribution.

For each possible state `x`:

```text
weight_1(x) =
    initial(x) * P(observation_1 | x)

belief_1(x) =
    weight_1(x) / sum of all first weights
```

For every later observation, the next state is predicted using the transition probabilities:

```text
prediction_k(x) =
    sum over y of:

    belief_(k-1)(y) * P(x | y)
```

The prediction is updated using the emission probabilities:

```text
weight_k(x) =
    prediction_k(x) * P(observation_k | x)
```

The weights are normalized:

```text
belief_k(x) =
    weight_k(x) / sum of all current weights
```

Transition tables are interpreted as:

```text
transition[current_state][next_state]
```

Emission tables are interpreted as:

```text
emission[hidden_state][observed_level]
```

Forward filtering combines contributions from all possible hidden-state histories.

Viterbi instead finds a single most likely hidden-state sequence. The complete final state distribution is more suitable here because routing uses the probability of High traffic rather than a reconstructed historical sequence.

Normalization at each step helps avoid very small probability products over long histories.

Impossible observations raise an error instead of producing an arbitrary fallback distribution.

### Initial probabilities

The initial probabilities are scenario-specific.

| Scenario | Low | Medium | High |
| --- | ---: | ---: | ---: |
| 1 | 0.60 | 0.30 | 0.10 |
| 2 | 0.50 | 0.35 | 0.15 |
| 3 | 0.60 | 0.30 | 0.10 |

A road with no observations uses these initial probabilities directly.

The implementation does not replace missing history with an assumed Low state or a guessed long-run distribution.

### Worked traffic example

For road H2 -> N8 in Scenario 2, the historical observations are:

```text
Low, Medium, High, Medium, High
```

The transition and emission rows, in Low/Medium/High order, are:

| Hidden state | Transition probabilities | Emission probabilities |
| --- | --- | --- |
| Low | .75, .22, .03 | .80, .18, .02 |
| Medium | .15, .70, .15 | .15, .70, .15 |
| High | .03, .22, .75 | .02, .18, .80 |

The initial distribution is:

```text
(0.50, 0.35, 0.15)
```

The first observation is Low.

Applying its emission probabilities gives:

```text
Low:       0.50 * 0.80 = 0.4000
Medium:    0.35 * 0.15 = 0.0525
High:      0.15 * 0.02 = 0.0030
```

The weights sum to:

```text
0.4555
```

After normalization, the first belief is approximately:

```text
(0.878155872667,
 0.115257958288,
 0.006586169045)
```

The second prediction, before including the Medium observation, is:

```text
(0.676103183315,
 0.275323819978,
 0.048572996707)
```

Applying the emission probabilities of the second observation gives:

```text
(0.121698572997,
 0.192726673985,
 0.008743139407)
```

These weights sum to:

```text
0.323168386389
```

Repeating the prediction and update steps produces:

| Readings processed | P(Low) | P(Medium) | P(High) |
| ---: | ---: | ---: | ---: |
| 1 | .878155872667 | .115257958288 | .006586169045 |
| 2 | .376579449360 | .596366111606 | .027054439034 |
| 3 | .041359105118 | .421349 | .537292218420 |
| 4 | .049706783670 | .739730632892 | .210562583438 |
| 5 | .010113305926 | .282220273412 | .707666420662 |

After the five readings, the probability of High traffic is approximately 70.8%.

The reverse road N8 -> H2 has no observations and retains the Scenario 2 initial distribution:

```text
(0.50, 0.35, 0.15)
```

Historical observations are processed separately for each directed road.

### Availability of traffic histories

| Scenario | Directed roads | Roads with history | Total observations |
| --- | ---: | ---: | ---: |
| 1 | 14 | 14 | 140 |
| 2 | 30 | 3 | 15 |
| 3 | 60 | 10 | 100 |

The traffic belief retains:

- The complete probability distribution.
- The number of observations used.
- Whether only the initial distribution was used.

Missing historical evidence therefore remains distinguishable from a distribution that has been updated using observations.

### Separating traffic from travel duration

Bayesian road probabilities determine estimated travel time.

HMM traffic probabilities provide a separate route preference.

The implementation does not multiply Bayesian and HMM slowdown factors or take the maximum of the two.

Combining slowdown factors in those ways could count congestion twice or change the assignment's travel-time interpretation of Open and Congested roads.

The supplied data does not provide a joint probability model connecting the Bayesian road conditions with the HMM traffic states.

### Traffic-exposure score

Each road contributes a traffic-exposure value:

```text
edge_exposure =
    normal_seconds * P(High | historical observations)
```

The exposure score of a route is:

```text
Q(route) =
    sum of edge_exposure over every road traversal
```

The contribution is weighted by normal travel duration.

A longer road contributes more exposure than a shorter road with the same probability of High traffic.

Repeated traversals contribute repeatedly to exposure because the score measures travel along roads, rather than the probability of a fixed road being blocked.

The score:

- Is not additional travel time.
- Is not a road blockage probability.
- Is not a guarantee of road safety.
- Does not require independence between traffic states on different roads.

The full Low/Medium/High probability distribution remains available, although the route score uses only the probability of High traffic.

### Available routing policies

| Policy | Behaviour |
| --- | --- |
| `bayesian-only` | UCS minimizes estimated Bayesian travel time. |
| `hmm-tie` | Minimize travel time first and traffic exposure second. |
| `hmm-bounded` | Permit a limited detour when it provides a sufficient reduction in traffic exposure. |

The exact-tie policy compares travel times using exact equality rather than rounded values or a tolerance.

The bounded policy works as follows:

1. Find the fastest reference route, using exposure to break exact travel-time ties.
2. Let its travel time be `T_ref` and its exposure be `Q_ref`.
3. Search for the lowest-exposure route within the allowed travel-time budget.
4. Break exposure ties using travel time.
5. Accept the alternative only if its exposure is strictly lower and the minimum reduction requirement is met.
6. Otherwise retain the reference route.

The maximum permitted travel time is:

```text
T_limit =
    (1 + max_extra_fraction) * T_ref
```

The alternative must satisfy:

```text
Q_alternative < Q_ref
```

and:

```text
Q_alternative <=
    (1 - min_exposure_reduction) * Q_ref
```

The main comparison settings are:

```text
max_extra_fraction = 0.05

min_exposure_reduction = 0.10
```

These allow up to 5% extra estimated travel time for at least a 10% reduction in traffic exposure.

Both fractions must be finite and between zero and one.

A zero travel allowance gives the exact-tie policy.

A reference route with zero travel time or zero exposure does not produce a detour.

### Search with multiple criteria

Ordinary UCS can discard a slower path to a node when a faster path is already available.

With traffic exposure as a second criterion, that slower path may still be useful.

For example:

```text
Path A:
    Travel time = 10
    Exposure = 8

Path B:
    Travel time = 11
    Exposure = 2
```

Neither path is better in both criteria.

The bounded traffic search therefore maintains multiple labels at a node.

A label contains its accumulated travel time and accumulated exposure.

A label can be discarded when another label reaches the same node with:

- No greater travel time.
- No greater exposure.

This dominance rule preserves alternatives that could contribute to a better route within the travel-time allowance.

Nonnegative costs prevent cycles from providing a useful improvement. However, the number of nondominated alternatives can still grow very large.

The search uses a configurable generated-label limit. The default limit is 100,000.

Exceeding this limit raises `TrafficSearchLimit` instead of returning an unproved result as if it were optimal.

### Deadline interaction

In strict mode, the available travel-time budget is also limited by the incident deadline:

```text
remaining_budget =
    deadline - current_time
```

A selected route must fit within this remaining budget.

The simulator checks the resulting absolute arrival time again before accepting the assignment.

A shortest-route fallback handles floating-point subtraction boundaries near a deadline.

Allow-late mode does not impose a hard arrival-deadline cap on route selection. A traffic-preferred detour can therefore turn an otherwise on-time route into a late route.

CP-SAT receives the selected route and its resulting on-time flag.

The allocation model receives one selected route per responder-incident pair. It does not jointly optimize over multiple alternative routes for the same pair.

### Observed traffic-policy effects

The traffic-policy comparison found seven changed endpoint routes in Scenario 3.

None of those changed routes was used by an actual dispatched responder in the evaluated simulations.

The assignments, committed routes, handled counts and response times remained unchanged.

For one endpoint pair, N3 -> H1, the bounded alternative had approximately 2.22% more estimated travel time and 44.96% less traffic exposure.

These results show that the HMM-based policy can affect route selection, but do not demonstrate improved dispatch outcomes for the supplied scenarios.

The comparison uses the original 5% and 10% settings throughout.

---

## 4. Search algorithms

### Uniform Cost Search

Uniform Cost Search is the normal shortest-path algorithm.

The road network is represented as a directed graph with fixed, nonnegative travel costs.

UCS orders its priority queue by:

```text
g(n) = accumulated travel cost from the start to n
```

The search maintains:

- A priority queue of discovered paths.
- The cheapest discovered cost for each node.
- Predecessor information for path reconstruction.

A newly discovered path is queued only when it strictly improves the best known cost of its destination.

Older queue entries are skipped when a cheaper discovery has replaced them.

The goal is accepted when it is removed from the priority queue, not when it is first discovered.

For a finite fixed graph with nonnegative representable edge costs, UCS finds a minimum-cost route under the supplied costs.

Its guarantee applies to the estimated travel costs, not the unknown actual road conditions.

The implementation supports directed roads, parallel edges, zero-cost cycles and unreachable destinations.

A search from a node to itself returns a one-node route with zero travel time.

An unreachable destination returns no route.

Overflow in accumulated travel cost raises an error rather than making a path appear unreachable.

A new search is required if the graph costs change.

### A* search

A* is implemented as a separate comparison with another search method from the course.

It uses:

```text
f(n) = g(n) + h(n)
```

Here:

- `g(n)` is the accumulated travel cost.
- `h(n)` estimates the remaining cost.

The project uses the following heuristic:

```text
h(n) =
    straight_line_distance(n, goal)
    / maximum_road_speed
```

The heuristic builder checks that road distances are not shorter than their geometric distance and that graph costs are at least the corresponding normal road times.

Under these conditions, straight-line distance divided by maximum speed provides a lower bound on the remaining travel time.

The triangle inequality supports this lower-bound property.

Congestion increases travel costs, while removing roads cannot produce a shorter minimum route. Both preserve the lower-bound property.

Floating-point arithmetic can introduce small numerical differences.

### A* implementation properties

The A* implementation can reopen a node when a cheaper path is discovered.

This also supports admissible but inconsistent caller-supplied heuristics.

Arbitrary heuristic callbacks must satisfy the documented conditions. The implementation cannot automatically prove that every supplied heuristic is admissible.

Invalid heuristic values and accumulated-cost overflow are rejected.

The returned route contains its actual accumulated travel cost, not the priority value `f(n)`.

Equal-cost routes may differ between UCS and A*.

With a zero heuristic, A* follows the same lowest-cost-first principle as UCS.

### Search comparison

A* is used for comparison and testing rather than normal dispatch.

The tests compare both algorithms on:

- 845 ordered scenario node pairs using normal road costs.
- 845 ordered scenario node pairs using Bayesian road costs.
- 750 small-graph cases checked against exhaustive simple-path calculations.

The comparisons verify minimum travel costs and path validity.

Different paths with equal minimum costs are allowed.

UCS remains the normal search algorithm.

No A* runtime comparison was performed, so the results do not establish a speed improvement.

See [TESTING.md](TESTING.md) for the search tests.

---

## 5. Event-based simulation

### Simulation state

The simulator maintains:

- A private graph copy.
- An event queue.
- The current simulation time.
- Current responder states.
- Revealed incident states.
- Committed assignments.
- Event and decision records.

The simulation advances directly to the next relevant event rather than checking every simulated second.

Relevant events include:

- Incident releases.
- Initial responder availability.
- Responder arrivals.
- Treatment completions.
- Arrival deadlines.
- Explicit scripted decision times.

### Decision snapshots

At each decision, the simulator creates a `DecisionSnapshot` containing:

- The current simulation time.
- Revealed incidents.
- Current responder states.
- Eligible responder-incident pairs.
- The selected deadline policy.

The allocator does not receive the complete scenario or future event queue.

Input loading can read all scenario incidents, but unreleased incidents are not included in the allocator's decision snapshot.

This prevents accidental use of future incident information through the normal allocation interface.

An arbitrary external Python callback could still read external files independently. The snapshot interface is not a security sandbox.

### Candidate generation

A responder-incident pair is eligible only if:

- The incident has already been released.
- The incident is still pending.
- The responder is currently available.
- The responder has the required capability.
- A route exists under the selected road policy.
- The route satisfies the current deadline policy.

The candidate contains the selected route, estimated arrival, treatment completion time and whether arrival is on time.

A route with an estimated arrival after the deadline is excluded in strict mode.

Allow-late mode retains otherwise eligible late candidates.

### Dispatch validation

The dispatcher returns responder and incident IDs.

The simulator validates the complete returned batch before committing any assignment.

Repeated responders, repeated incidents and ineligible pairings cause an error.

An invalid batch is not partly committed.

Events processed before an invalid callback are not rolled back.

### Responder and incident states

Responder states are:

```text
initially_busy
available
travelling
treating
```

During travel, the responder's location is `None`.

Arrival places the responder at the incident location and starts treatment.

Treatment completion makes the responder available at that location.

Incident work states are:

```text
pending
travelling
treating
completed
closed_unassigned
```

Deadline status is maintained separately:

```text
not_due
met
missed
```

This allows an incident to be completed while having a missed deadline in allow-late mode.

### Simultaneous events

Releases, arrivals, completions and initial readiness at the same timestamp are processed before requesting new assignments.

The event queue uses an insertion counter to provide stable ordering for equal timestamps.

Zero-travel arrivals and zero-treatment completions are processed before closing pending incidents at their deadline.

Several decisions may occur at exactly the same simulation time when zero-duration assignments finish.

Each incident can be assigned at most once. This ensures that chains of zero-duration assignments terminate for a finite incident stream.

A deadline before an incident's release is marked missed when the incident is released. No event is created in the past.

### Advancing time

An empty allocation does not terminate the simulation while future relevant events remain.

The simulator continues processing later releases and responder availability changes.

All committed assignments are completed.

Deadlines that have already been met do not unnecessarily extend the simulation.

The final simulation time is the last relevant processed event, including an initial availability event or an explicit scripted wake-up.

### Closing unhandled incidents

In strict mode, an incident that remains unassigned after its deadline is closed with:

```text
strict_deadline_unassigned
```

In allow-late mode, pending incidents remain available for assignment until no relevant events remain.

An incident that cannot be assigned before the end of the run is closed with:

```text
no_more_events_unassigned
```

The absence of an eligible candidate at one decision does not establish that no eligible candidate could become available later.

### Numerical handling

Simulation times use floating-point seconds.

Nearby timestamps are not merged through display rounding.

Arrival and deadline checks use the underlying unrounded values.

Overflow raises `ValueError`.

A positive duration that is too small to advance an extremely large floating-point clock also raises `ValueError`.

An integer-based simulation clock would require a separate rounding policy.

Solver wall-clock runtime does not advance simulation time.

### Scripted execution

Scripted assignments are available for testing the simulation.

A script can supply assignment requests at explicit decision times.

Each scripted timestamp is consumed once, including during zero-duration chains.

Scripts may be created with knowledge of the full scenario. They test whether execution rules are enforced rather than establish online planning quality.

---

## 6. CP-SAT allocation

### Variables and constraints

The allocation model uses Boolean variables for eligible responder-incident pairs:

```text
x[r, i] = 1 if responder r is assigned to incident i

x[r, i] = 0 otherwise
```

A variable is created only when the simulator has identified an eligible candidate.

The responder constraint is:

```text
For every responder r:

    sum over i of x[r, i] <= 1
```

The incident constraint is:

```text
For every incident i:

    sum over r of x[r, i] <= 1
```

An incident assignment variable can also be expressed as:

```text
y[i] = sum over r of x[r, i]
```

Since `y[i]` is Boolean, at most one responder may be assigned to the incident.

The model permits incidents to remain unassigned.

An empty allocation is therefore feasible.

An unexpected infeasible model indicates a model or implementation problem rather than simply a lack of eligible assignments.

### Objective order

The objectives are optimized in lexicographic order:

1. Maximize the number of Critical assignments.
2. Maximize the number of High assignments.
3. Maximize the number of Medium assignments.
4. Maximize the number of Low assignments.
5. In allow-late mode, maximize on-time assignments by priority while preserving the previous coverage results.
6. Minimize total predicted response time.

Each priority count is optimized separately.

An objective value is fixed only after the solver has proved it optimal.

Later objective stages must preserve the previously fixed values.

This avoids having to use arbitrary numerical weights to represent the relative importance of incident priorities.

Coverage is optimized before response time because minimizing total response time alone could select an empty allocation with a total cost of zero.

### Response-time objective

The response-time objective uses the predicted arrival time minus the incident release time.

It includes waiting time before dispatch.

For each candidate:

```text
response_seconds =
    estimated_arrival - incident_release
```

The integer cost used by CP-SAT is:

```text
response_milliseconds =
    ceil(1000 * response_seconds)
```

The conversion rounds up to integer milliseconds.

Integer-range checks are applied to the objective coefficients.

The original floating-point travel and arrival times remain unchanged in the simulator.

Consequently, rounding affects the optimization objective but not hard deadline feasibility.

Very close response times may be ordered differently by the integer objective than by their full-precision values.

### Objectives that are not included

The current allocation model does not separately optimize:

- Earliest deadline ranking.
- Remaining deadline slack.
- Waiting age.
- Treatment duration.
- Complete route blockage risk.
- Preservation of responders with scarce capabilities.
- Future responder positions.
- Reservations for later assignments.

Deadlines are used as feasibility conditions in strict mode and as on-time indicators in allow-late mode.

The allocation model optimizes the currently known incidents and available responders.

It does not schedule several jobs ahead.

In allow-late mode, a late Critical assignment can rank above an on-time High assignment because priority coverage is optimized before on-time coverage.

This can reduce the total percentage of on-time arrivals.

### Solver time budget

All objective stages share a configurable wall-clock time budget.

The default is two seconds per allocation decision.

Elapsed model-building time is included when determining the remaining solve budget.

Python model-construction work cannot be interrupted exactly at the specified limit.

The solver uses:

```text
Number of workers: 1

Random seed: 0
```

Variable and constraint ordering is stable.

Exact equal-cost tie choices may nevertheless differ across solver versions, platforms or execution conditions.

### Solver outcomes

| Outcome | Behaviour |
| --- | --- |
| `OPTIMAL` | Retain the solution, fix the proved objective and continue to the next stage. |
| `FEASIBLE` | Retain the valid solution and stop without claiming optimality. |
| `UNKNOWN` or exhausted budget | Retain the most recent valid solution, or return no assignments if none exists. |
| `MODEL_INVALID` | Raise `AllocationError`. |
| `INFEASIBLE` | Raise `AllocationError` because the empty allocation should be feasible. |
| Unexpected status | Raise `AllocationError`. |
| `NO_CANDIDATES` | Return an empty decision without running the solver. |

Objective stages that are always zero are skipped.

Diagnostics retain the solver status, objective values, bounds, elapsed time and whether all relevant objective stages were proved optimal.

A timeout does not automatically start another solve budget or switch to the nearest-responder allocator.

### Nearest-responder baseline

The comparison allocator uses the same eligible candidate pairs as CP-SAT.

It sorts candidates by:

1. Estimated travel time.
2. Responder ID.
3. Incident ID.

It then selects candidates greedily, provided neither the responder nor the incident has already been selected in the current batch.

The nearest-responder method does not optimize:

- Incident priority.
- Waiting age.
- Late-mode on-time coverage.
- The complete set of competing assignments.

A greedy choice can assign a responder with a useful capability to an incident that another responder could have handled.

This may affect later coverage.

The nearest-responder allocation baseline is separate from the all-open routing baseline.

### Scenario 3 allocation result

Under strict deadlines, CP-SAT handles 13 of 20 incidents in Scenario 3.

The nearest-responder comparison handles 15 of 20.

For the initial First aid incident I4, R1 and R2 have equal estimated travel costs.

CP-SAT selects R2, while the nearest-responder comparison selects R1.

R1 also has the Medical emergency capability, which R2 lacks.

Their different assignments lead to different locations and availability for later incidents, including I11 and I14.

This illustrates a limitation of immediate allocation: optimizing the current batch does not guarantee an optimal plan over the complete incident sequence.

The measured comparison results are documented in [TESTING.md](TESTING.md).

---

## 7. Output files and independent validation

### Plan format

The required `plan.json` file contains a list of assignment records.

Each record has exactly four fields:

```json
[
  {
    "responder_id": "R1",
    "incident_id": "I1",
    "path": ["N1", "H1", "N2"],
    "time": 0
  }
]
```

This example illustrates the file format. It does not establish that the particular assignment is feasible in a specific scenario.

The fields represent:

| Field | Meaning |
| --- | --- |
| `responder_id` | The assigned responder. |
| `incident_id` | The incident being handled. |
| `path` | Ordered node IDs along the selected route. |
| `time` | Absolute dispatch start time in seconds. |

The path includes both the starting and destination nodes.

An assignment where the responder is already at the incident location has a one-node path.

Fractional departure times are preserved.

A responder may appear in multiple records when completing separate assignments over time.

Unhandled incidents have no assignment record.

Arrival times, treatment completion times, probability distributions, traffic scores and configuration settings remain outside the required four-field schema.

### Statistics

The `statistics.txt` file contains the required summary measurements.

| Statistic | Definition |
| --- | --- |
| Handled incidents | Incidents whose treatment has finished, including permitted late responses. |
| Responders used | Distinct responders with committed assignments. |
| Average response time | Mean arrival time minus release time for handled incidents. |
| Deadline percentage | On-time arrivals divided by all incidents. |

Response time includes waiting and travel but excludes treatment.

Unhandled incidents are excluded from the average response time.

Unhandled incidents count against the overall deadline percentage.

If no incidents are handled, average response time is displayed as N/A.

If no incidents exist, the deadline percentage is displayed as N/A.

The underlying statistics also retain the percentage of on-time arrivals among handled incidents.

The text output additionally includes:

- Coverage by priority.
- Late incident counts.
- Unhandled incident IDs.
- Critical incident coverage.
- Validation results.
- Routing and allocation settings.
- Explanations for unhandled incidents.

Display values may be rounded, but the simulation and plan retain the underlying numerical precision.

Average response time must be interpreted alongside coverage because different planning policies may handle different incidents.

### Export behaviour

The exporter copies the assignments already committed by the simulator.

It does not perform another route search or allocation.

Before writing output files, it validates the plan and compares independently reconstructed results with the original simulation.

The comparison checks:

- Travel durations.
- Arrival times.
- Treatment completion times.
- Calculated statistics.

A mismatch raises an error before the files are written.

### Independent plan validator

The validator receives the original scenario data and the decoded assignment plan.

It checks:

1. The exact required plan fields.
2. Known responder, incident and node IDs.
3. Finite, nonnegative departure times.
4. Incident uniqueness.
5. Required responder capabilities.
6. Incident release times.
7. Initial and later responder availability.
8. The responder's current departure location.
9. Valid directed road connections.
10. The correct incident destination.
11. Compliance with the selected road cutoff.
12. Reconstructed travel duration.
13. Treatment completion and assignment overlap.
14. Arrival deadlines.

The validator independently reconstructs road filtering, travel durations, responder timelines and statistics.

It does not use:

- The simulator.
- The graph builder.
- The route search algorithm.
- The allocation model.
- The original statistics summary function.

The Bayesian inference calculation and statistics record type are shared with the application.

Separate probability tests are therefore still necessary to check the shared inference arithmetic.

### Chronological replay

Plan rows are replayed in increasing departure-time order.

The original row order breaks ties between equal departure times.

The input rows do not need to be supplied in chronological order.

A responder may start a new assignment exactly when the previous treatment finishes.

Zero-duration travel and treatment may also permit multiple assignments at the same timestamp.

Malformed JSON, repeated keys, NaN and Infinity are rejected.

Invalid plans produce errors identifying the relevant row or rule.

Performance statistics are not returned for invalid plans.

### Meaning of validation

A valid plan follows the selected rules and modeled travel times.

A deadline-compliant plan additionally requires that every assigned responder arrives on time.

Neither condition guarantees good incident coverage.

For example, an empty plan can satisfy the assignment constraints while handling no incidents.

An allow-late plan must be validated using the corresponding relaxed deadline policy.

The required plan format does not store routing or deadline settings.

The caller must therefore supply the same road policy, blockage cutoff and deadline mode that were used to generate the plan.

The validator does not infer or modify those settings.

The standalone `validate_plan.py` command does not require OR-Tools.

Its exit codes are:

| Exit code | Meaning |
| ---: | --- |
| 0 | Valid plan under the selected rules. |
| 1 | Invalid plan. |
| 2 | File or configuration error. |

A valid exported plan does not establish that the allocator lacked access to future information. Decision-snapshot tests check that property separately.

The validator also does not establish whole-scenario optimality or guarantee real-world arrival times.

---

## 8. Explanations for unhandled incidents

### Purpose

The diagnostic component explains why incidents remained unassigned during a particular simulation run.

It does not change routing, allocation, timing, deadlines or existing performance measurements.

The component copies the eligibility checks already performed by the simulator and records the assignments actually committed.

It performs no additional route searches, allocation solves or simulation events.

### Recorded information

For each revealed, pending incident and responder, diagnostics record:

- Required capability.
- Responder capabilities.
- Availability.
- Current status and location.
- Expected availability time.
- Whether a usable route exists.
- Estimated arrival when a route is actually checked.
- Whether the estimated arrival meets the deadline.
- Whether the pair satisfies the selected deadline policy.

Capability is checked before availability when identifying the first failed eligibility condition.

Both Boolean results are retained.

For busy or unqualified responders, route and arrival fields are marked as not checked.

This is different from finding that no route exists.

### Decision records

Each decision record contains:

- Absolute simulation time.
- Incident deadline.
- Decision sequence number.
- Candidate checks.
- Selected assignment batch.
- Available solver outcome information.

Multiple decisions at the same timestamp have separate sequence numbers.

When an eligible responder is assigned to another incident, the diagnostic records the actual competing assignment.

It does not assume that a particular priority rule was the sole reason for the choice.

A solver timeout is not described as a proved optimal allocation.

An eligible late candidate is not described as an on-time candidate.

Non-CSP dispatchers do not have CP-SAT solver statuses.

### Final summaries

Only incidents that finish the simulation unassigned receive final explanations.

Each explanation includes:

- Whether an eligible on-time candidate was ever checked.
- The earliest estimated arrival that was actually calculated.
- The corresponding responder and decision time.
- The incident deadline.
- How late the checked arrival would have been, where applicable.
- The closure reason.
- The recorded decision history.

The earliest checked arrival may itself be late.

No arrival is invented for a responder whose route was not checked.

An incident with a strict deadline before its release may close without ever producing a pending decision record.

The final display snapshot is not treated as an additional dispatch decision.

### Output representation

The `statistics.txt` file contains a short explanation for each unhandled incident.

The complete history is retained in:

```text
SimulationResult.unhandled_explanations
```

Explicit CLI JSON includes the same records under:

```text
simulation.unhandled_explanations
```

Diagnostic recording can be disabled using:

```python
simulate(
    scenario,
    graph,
    dispatcher,
    record_diagnostics=False
)
```

This option is used to compare execution with and without diagnostic recording.

### Diagnostic limitations

The explanations describe the states reached during the actual simulation.

They do not prove that an incident was impossible to handle under every alternative allocation.

Earlier assignments influence later responder positions and availability.

Changing the allocation policy, road cutoff or deadline policy could therefore change which incidents become reachable later.

Recording requires memory proportional to the responder-incident checks performed across decisions.

The CP-SAT wall-clock budget remains unchanged. Different machine loads can still affect solver outcomes when the time budget is reached.

A separate 48-run comparison verified that the original assignments, event logs, final states, timings and statistics remained unchanged when diagnostic recording was added.

See [TESTING.md](TESTING.md) for the regression checks.

---

## 9. Execution configurations

### Normal menu execution

Running:

```console
python run.py
```

opens the scenario menu.

The menu uses the complete planner with the following settings:

| Component | Configuration |
| --- | --- |
| Road inference | Bayesian Networks |
| Blockage cutoff | 0.20 |
| Historical traffic inference | HMM Forward filtering |
| Traffic routing | `hmm-bounded` |
| Maximum extra travel | 0.05 |
| Minimum exposure reduction | 0.10 |
| Normal shortest-path search | UCS |
| Allocation | CP-SAT |
| Deadline policy | Strict deadlines |
| Diagnostic recording | Enabled |

The program prints and saves the required output files.

Menu results are stored in:

```text
results/menu/ScenarioN/plan.json

results/menu/ScenarioN/statistics.txt
```

Running the same scenario again replaces the previous files in that scenario folder.

### Explicit command-line execution

Explicit scenario commands use the all-open routing baseline unless Bayesian routing is selected.

The all-open baseline assigns normal travel times to all roads and does not apply Bayesian blockage filtering.

This allows optimistic routing comparisons and isolated search tests.

Explicit Bayesian runs require the blockage threshold to be supplied.

Normal and scripted explicit runs write output files in the current directory unless `--output-dir` is provided.

Comparison runs use separate `csp` and `nearest` output folders.

Route-only inspection does not write assignment files and rejects a nondefault output directory.

Explicit commands print diagnostic JSON. The normal menu prints the saved plan and statistics.

The complete commands are documented in [README.md](README.md).

### File and state handling

Repeated runs replace files with the same output names.

The two output file writes are separate operations rather than one atomic filesystem transaction.

File input/output errors propagate to the caller.

The original scenario input and graph objects are not modified by routing and simulation execution.

---

## 10. Current limitations and unimplemented extensions

The following sections describe limitations of the implemented system and possible extensions.

These extensions are not part of the current planner and have not been evaluated as implemented features.

### Actual road failures

The simulator follows estimated travel durations.

It does not simulate the actual Open, Congested or Blocked condition of a road being discovered during travel.

There are no events for:

- Discovering an actual blockage.
- Turning back from a blocked road.
- Losing time because of a road failure.
- Finding a replacement route during a journey.
- Updating road beliefs from newly discovered conditions.

A possible extension would introduce actual road-condition outcomes and recovery behaviour.

Such an extension would require rules for where the responder is located when a blockage is discovered, how much time has already been spent and how a replacement route affects the remaining deadline.

The supplied inputs do not provide true road-state outcomes against which the current probability estimates can be validated.

### Live traffic information

The HMM uses historical observations processed before the simulation.

The current system does not receive new traffic readings while responders are travelling.

The historical sequences do not establish how traffic changes during the emergency simulation.

Live filtering would require a definition of observation timing, new observations and their relationship to simulation time.

### Critical fallback routing

The current road cutoff is identical for all incident priorities.

A proposed extension would allow higher-risk routes for Critical incidents when the normal road policy cannot provide sufficient on-time Critical coverage.

A batch-level comparison could consider:

1. Allocation using only normal-cutoff routes.
2. Allocation using normal routes and additional Critical fallback candidates.

The expanded allocation would only be considered after demonstrating an increase over the normal-only Critical coverage.

If the normal-only optimum cannot be established within the solver budget, the comparison may remain inconclusive.

The normal allocation would then be retained under a conservative fallback policy.

Considering the complete batch is necessary because different Critical incidents may compete for the same normal responder.

Removing fallback options independently for each incident could eliminate an allocation that reaches more Critical incidents.

Two possible objective policies are:

- Preserve the existing Critical-first priority order, allowing additional Critical coverage to displace lower-priority assignments.
- Protect the normal allocation's lower-priority coverage counts before accepting a Critical improvement.

These are different planning policies. Neither has been implemented or evaluated in the current system.

After coverage objectives, a fallback allocation could minimize unnecessary fallback usage and compare route risk before response time.

The maximum individual road blockage probability does not establish the blockage probability of the complete route.

A predicted arrival through a fallback route would still assume the route is passable.

Evaluating the extension would therefore require both modeled coverage and additional risk measurements.

The validator would also need to support the expanded road policy and independently check whether fallback eligibility was justified by the normal-only allocation.

The required four-field plan schema could remain unchanged.

### Waiting for a busy responder

The current allocator only assigns responders who are available at the current decision.

A responder may accept another incident immediately after finishing treatment.

However, the system does not reserve a responder for a future assignment or deliberately delay a dispatch to wait for a currently busy responder.

A possible extension would compare immediate dispatch with waiting for a qualified responder to become available.

For example, a busy responder might already be at the location of another incident and become available before its deadline.

Such an extension would require explicit waiting and reservation rules.

A larger scheduling model could consider several already known incidents over a longer planning horizon.

These behaviours are not implemented.

### Patient transport and station returns

Currently, a responder becomes available at the incident location immediately after treatment finishes.

An ambulance does not subsequently transport a patient to a hospital.

No hospital handover time is included.

Responders do not automatically return to their stations.

A proposed extension would model these additional journeys and their effect on availability.

For ambulance transport, the model would need to include:

- The selected hospital.
- Travel time from the incident to the hospital.
- Hospital handover duration.
- Availability after handover.

For station returns, the model would need to define:

- The destination station.
- Return travel time.
- Whether a returning responder can accept another assignment.
- The responder's location if a new call appears during the journey.

Returning to a station and remaining at the incident may produce different starting locations for future responses.

These effects would need a separate comparison.

### Evaluation requirements for extensions

The proposed extensions would require additional tests and experiments.

Critical fallback would require a comparison of additional modeled on-time coverage against additional accepted blockage risk.

Actual road failures would require tests for discovering blockages, recovery time, replacement routes and updated deadlines.

Patient transport and station returns would require checks for additional travel time, handover time, availability and departure location.

Deliberate waiting and future reservations would require tests for scheduling conflicts and the effect of delaying immediate assignments.

These evaluations have not been performed because the extensions are not implemented.

---

## Summary

The implemented system combines Bayesian road inference, HMM Forward filtering, directed-graph search and CP-SAT allocation within an event-based simulation.

Its normal execution uses strict arrival deadlines, a 20% road blockage cutoff and a bounded historical traffic preference.

The system generates the required assignment plan and statistics, independently validates the exported plan and records explanations for unhandled incidents.

The planner operates on estimated travel times and currently known incidents. Its results do not establish guaranteed road safety, calibrated traffic prediction accuracy or whole-scenario optimality.

The source implementation is described in [CODE_GUIDE.md](CODE_GUIDE.md).

The tests and measured results are documented in [TESTING.md](TESTING.md).

Installation and execution instructions are available in [README.md](README.md).

The development discussions, rejected suggestions and LLM collaboration are documented separately in [LLM_NOTES.md](LLM_NOTES.md).
