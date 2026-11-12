
# My design decisions and use of the LLM

> **Note:** This document is an AI-assisted summary of the most important prompts, discussions and design decisions throughout the project. It reflects how I used the LLM, the suggestions I questioned, and the decisions that shaped the final implementation. The main findings and most important examples of my LLM collaboration are summarized more briefly in the final report.


## Introduction

The aim of this project was to build an Emergency Response System that decides which responders should handle incidents after a storm and which routes they should take.

I wanted to design a system that combines the four AI techniques from the course: search, Bayesian reasoning, Hidden Markov Models and Constraint Satisfaction Problems. The main challenge was deciding how these techniques should work together, since they each solve a different part of the problem.

I used ChatGPT to discuss my ideas and work through the mathematical reasoning. I used Codex to help translate the design into Python, generate tests and investigate implementation problems.

Throughout the project, I tried to understand each component before moving on to the next one. I made decisions about the system's behaviour, questioned assumptions that I was not convinced by, and compared different approaches.

This document explains how I developed the design and how the discussions with the LLM influenced the final implementation.

The technical details of the final system are explained in [DESIGN.md](DESIGN.md). The tests and their results are documented in [TESTING.md](TESTING.md).

---

## 1. Designing the overall system

Before starting the implementation, I wanted to understand the problem as a whole.

The assignment requires the use of four AI techniques, but it leaves several decisions about their integration open. I wanted each technique to have a clear responsibility rather than combine everything into one large algorithm.

I divided the problem into the following parts:

- Bayesian reasoning estimates the condition of each road.
- An HMM estimates traffic levels using historical observations.
- Search finds routes through the road network.
- A CSP chooses which responder should handle each incident.
- A simulation keeps track of time, incidents and responder availability.

My idea was to make the probability models provide information to the routing component. The resulting routes could then be used by the CSP to decide which assignments were possible.

The simulation would connect these components and update the situation whenever an incident appeared or a responder became available.

I wanted this separation because it would make the system easier to understand and test. For example, I should be able to check whether the Bayesian probabilities are correct without running the entire emergency simulation.

I discussed this architecture with ChatGPT before asking Codex to implement the components.

### Starting from the actual data

I did not want to design the system based only on a general description of an emergency-response problem. The supplied scenario files define what information is actually available.

I therefore asked the LLM to inspect the assignment, the scenarios and the relevant course slides before continuing with implementation.

This exposed an important distinction that needed to be kept throughout the project.

The Bayesian road conditions are:

- Open
- Congested
- Blocked

The HMM traffic levels are:

- Low
- Medium
- High

An early discussion mixed these two concepts together. I pointed out that they describe different things.

A road with High traffic is not necessarily Blocked. In the same way, knowing that a road is Congested does not directly tell us the hidden traffic state estimated by the HMM.

I also clarified that the traffic observations are historical. The observation numbers indicate the order of past readings, not the time at which they arrive during the simulation.

These distinctions became important later when I decided how the Bayesian and HMM results should influence routing.

The scenario files also clarified the units:

- Distances are measured in metres.
- Speeds are measured in metres per second.
- Simulation times are measured in seconds.

I wanted the program to use these definitions consistently and reject invalid input rather than silently change the supplied data.

The complete interpretation of the scenario files is documented in [DATA_SCHEMA.md](DATA_SCHEMA.md).

### Building the system step by step

I chose to develop the system in stages.

I started with the loaders, directed graph and search algorithm. Once those worked, I moved on to Bayesian reasoning, simulation, allocation and HMM filtering.

I specifically asked not to implement all the remaining components at once. I wanted to understand and test each part before connecting it to the others.

This also made debugging easier. If a routing result was incorrect, I could investigate the graph, probabilities or search algorithm separately.

The first version assumed that all roads were Open. I used this as a simple starting point for testing the graph and search algorithm. It was not intended to be the final road-condition model.

---

## 2. Designing the Bayesian road model

The road reports in the scenarios are uncertain. Citizens, police and sensors can report different conditions for the same road.

I wanted the system to combine this evidence instead of treating any one report as the real road condition.

The Bayesian Network follows this structure:

```
Weather
   |
   v
Road condition
   |
   +--> Citizen report
   +--> Police report
   +--> Sensor report
```

The weather affects the probability of each road condition. The actual condition then affects the probability of receiving each report.

For a possible road condition s, the calculation is:

```
weight(s) =
    P(s | weather)
    * product of P(report | s)
```

The weights for Open, Congested and Blocked are divided by their total to obtain a probability distribution.

Before implementing this part, I asked ChatGPT to explain the calculation using the actual probability tables from the scenarios.

I wanted to be able to verify the result myself rather than only check that the code returned three numbers.

### Why I kept all three probabilities

One of the first possible approaches was to choose the most likely road condition and use that condition directly when building the graph.

I did not want to throw away the remaining uncertainty.

For example, road N1 -> N2 in Scenario 1 produces these Bayesian weights:

```
Open:       0.00012
Congested:  0.00384
Blocked:    0.00441
```

After dividing by their sum of 0.00837, the probabilities are approximately:

```
Open:        1.43%
Congested:  45.88%
Blocked:    52.69%
```

Blocked is the most likely condition, but its probability is only about 53%.

If we immediately classified this road as Blocked, we would lose the information about its other possible conditions.

I therefore decided to keep the full distribution and make the road-use decision separately.

This was an important design choice for me. The Bayesian model should estimate what we know about the road. The routing policy should decide what to do with that information.

### Choosing a blockage threshold

I wanted the planner to avoid roads that had a high chance of being blocked, but I also realized that excluding too many roads could make incidents unreachable.

My approach was to use a configurable probability threshold.

The main configuration excludes roads when:

```
P(Blocked) >= 0.20
```

I kept the threshold adjustable because I wanted to be able to study the effect of different risk levels.

The 20% value is not given by the assignment and is not a proven safe threshold. It is a planning choice used consistently in the main experiments.

This distinction matters because changing the threshold changes which routes are possible, even though the underlying Bayesian probabilities stay exactly the same.

For example, lowering the threshold can make a destination unreachable. Increasing it can provide a shorter route, but that route may depend on roads with a higher chance of being blocked.

### Deciding how uncertain roads affect travel time

The assignment gives three road-condition rules:

```
Open:       normal travel time
Congested:  1.5 times normal travel time
Blocked:    cannot be traversed
```

I wanted the travel estimates to respect these rules while still using the probabilities calculated by the Bayesian model.

The final estimate for an accepted road is:

```
estimated_time =
    normal_time
    * (P(Open) + 1.5 * P(Congested))
    / (P(Open) + P(Congested))
```

Here, normal time is the distance divided by the road's speed.

The denominator is important. The estimate assumes that the road is not blocked and calculates the average of the Open and Congested travel times under that assumption.

I wanted to keep this estimate in seconds because it is used to calculate arrivals and check deadlines.

Adding an arbitrary risk penalty directly to travel time would make it less clear whether a value represents an actual duration or a preference for safer roads.

### Thinking about complete route risk

I also questioned whether accepting roads individually below the threshold was enough to describe the risk of a complete route.

A route could contain several roads with a relatively small probability of being blocked. The chance of encountering at least one blockage can still be substantial.

I wanted the system to retain this information rather than describe every accepted route as safe.

The route reports therefore include the following bounds:

```
Lower bound:
    maximum blockage probability of any road in the route

Upper bound:
    minimum of 1 and the sum of the blockage probabilities
```

These bounds do not require an assumption that different road failures are independent.

The supplied data does not describe how road failures are related to each other. For example, roads in the same area could be affected by the same storm.

This is why I did not want to present one exact probability of a route failing without introducing another probability model.

The bounds are reported separately from travel time.

### Checking the Bayesian assumptions

The calculation multiplies the likelihoods of the available reports. This follows from the assumption that the reports are conditionally independent once the road condition is known.

I understood that this assumption could be a limitation.

If a citizen report is based on information from the police, for example, the two reports may not provide independent evidence.

The probability calculation could then become too confident.

The project uses the network and conditional probability tables supplied in the assignment, but I wanted this assumption to remain visible in the documentation.

---

## 3. Designing the simulation and responder availability

I wanted the emergency system to make decisions as incidents appeared, rather than calculate a complete plan using all future incidents.

This was important because the problem describes emergencies occurring over time.

An assignment made now can also influence later decisions. A responder might be occupied when another call appears, or might become available at a different location after finishing treatment.

For this reason, I designed the simulation around events:

- An incident is released.
- An initially busy responder becomes available.
- A responder arrives at an incident.
- Treatment finishes.

I used Codex to work out the implementation of the event queue and the tests for these rules.

The simulator processes events at the same time together before making another dispatch decision.

This prevents the order of simultaneous events from unnecessarily changing which responders or incidents are considered.

### Separating arrival from completion

I wanted to make sure that the deadline was interpreted correctly.

The deadline applies to the time when the responder reaches the incident, not the time when treatment finishes.

For example:

```
Incident release:      10 seconds
Responder departure:   15 seconds
Travel time:            20 seconds
Arrival:                35 seconds
Treatment duration:     10 seconds
Completion:             45 seconds
```

If the deadline is 40 seconds, this assignment meets the deadline.

However, the responder does not become available for another incident until time 45.

This distinction became part of the simulator's state.

A responder remains occupied from departure until treatment completion. Their next assignment starts from the location of the previous incident.

I also considered what should happen to a responder who is already busy when the simulation starts.

The scenario files give the remaining busy time but do not provide another destination for that initial job. I chose to assume that the responder becomes available at their supplied start location.

I documented this assumption rather than inventing an initial route.

### Should a missed deadline mean abandoning the incident?

An important question for me was what should happen when an incident cannot be reached before its deadline.

In a real emergency, arriving late may still be better than not sending help at all.

I questioned whether the original strict-deadline approach should be the only possible behaviour.

I decided to keep two modes:

- Strict mode: only assignments expected to arrive before or at the deadline are allowed.
- Allow-late mode: a responder can still be dispatched after the deadline.

Strict mode remains the main configuration because it directly follows the assignment's arrival-deadline requirement.

The allow-late mode is used as a separate experiment.

I wanted to distinguish the question of whether an incident was handled from whether its deadline was met.

An incident can therefore receive completed treatment and still count as late.

### Preventing the use of future incidents

I wanted the allocation algorithm to receive only information that would be known at the time of its decision.

The simulator can read the complete scenario and maintain the event queue, but the allocator receives a separate view containing:

- The current time.
- Released incidents.
- Current responder locations and availability.
- Eligible responder-incident pairs.

It does not receive the future event queue or the unreleased incidents.

This was a design decision I wanted to enforce through the program's structure, rather than simply tell the allocator not to look ahead.

I also requested tests for release times, initially busy responders, simultaneous events and consecutive assignments.

---

## 4. Designing the responder allocation problem

Once the system could estimate travel times and determine which responders were available, I wanted a method for deciding between competing assignments.

Choosing the nearest responder independently for each incident would not be enough. Two incidents might need the same responder, or one responder might have a capability that another lacks.

I chose to model the allocation as a CSP using OR-Tools CP-SAT, following the Boolean-variable approach from the course.

For each eligible responder-incident pair, the model contains:

```
x[r, i] = 1 if responder r is assigned to incident i
x[r, i] = 0 otherwise
```

I wanted the constraints to represent the actual assignment rules directly.

For each responder:

```
sum over incidents of x[r, i] <= 1
```

For each incident:

```
sum over responders of x[r, i] <= 1
```

This means that each responder can receive at most one new assignment in the current decision and each incident can receive at most one responder.

The simulation handles the longer-term availability rules.

A responder who is still travelling or treating another incident cannot receive a new assignment.

I also decided that the model should only contain variables for eligible pairs. Skills, availability, route existence and the deadline policy are checked before the solver runs.

### Deciding what the solver should optimize

This was one of the most important design decisions in the project.

Initially, minimizing response time seems like an obvious objective for an emergency-response system.

However, I noticed that if the assignments are optional, minimizing the total response time could give a strange result.

The solver could assign nobody and obtain a response time of zero.

I wanted the system to have a reason to handle emergencies before optimizing how quickly it could handle them.

I therefore chose the following objective order:

1. Maximize the number of Critical incidents assigned.
2. Maximize High, Medium and Low assignments, in that order.
3. In allow-late mode, maximize on-time assignments by priority while keeping the earlier coverage counts.
4. Minimize total predicted response time.

The priority counts are optimized separately.

Once an objective has been proven optimal, its value is fixed before the solver continues with the next objective.

I preferred this approach to choosing arbitrary large weights for the priorities.

It makes the meaning of the objective easier to explain: the solver cannot improve a lower-priority objective by reducing a higher-priority result that has already been fixed.

### Why I removed deadline ranking

During the design discussion, ChatGPT also proposed ranking incidents by their deadlines before minimizing response time.

I questioned whether this was really necessary.

Consider two incidents with the same priority. Both can be reached on time, but one has an earlier deadline.

I did not think that the earlier deadline alone should automatically force the system to choose a much longer response.

I wanted deadlines to determine whether an assignment was feasible, while response time would help choose between assignments with the same coverage.

For this reason, I chose not to include an additional deadline-ranking stage.

I also left out extra objectives based on waiting age or deadline slack.

These could be useful in another planning policy, but I wanted to keep the first allocation model understandable and avoid adding objectives without evaluating their effects.

### Keeping solver time separate from simulation time

CP-SAT uses integer objective coefficients. I therefore agreed with converting response-time values to integer milliseconds for the optimization.

The simulation still keeps the original fractional travel times.

I wanted to avoid changing the deadline calculation just because the solver requires integers.

The implementation also distinguishes between proven optimal solutions and valid solutions found before the solver's time limit.

I did not want the system to claim that every returned solution was optimal if the solver had not finished proving it.

### Choosing an online allocation model

I deliberately kept the allocation focused on the current situation.

The solver chooses immediate assignments for known incidents and available responders. It does not schedule several future jobs for each responder.

I wanted to keep the model close to the assignment problem from the course before considering a larger scheduling problem.

The consequence is that the system does not optimize responder positions or availability over the whole simulation.

This limitation became particularly important when comparing the final results.

---

## 5. Designing the routing algorithm

I chose Uniform Cost Search as the main shortest-path algorithm.

The road network is a directed graph. The cost of an edge is the estimated travel time of that road.

UCS explores paths in order of their accumulated cost:

```
g(n) = total estimated travel time from the start to n
```

I wanted to implement the algorithm directly in Python instead of using a routing library, so I could follow the search process and connect it to the course material.

The implementation uses a priority queue, keeps track of the cheapest discovered cost to each node, and stores the predecessor information needed to reconstruct the final route.

The destination is accepted when it is removed from the queue, rather than when it is first discovered.

This is important because another path to the destination might still have a lower cost.

The search finds a shortest route for the supplied fixed, nonnegative edge costs.

However, those costs are estimates produced using uncertain road information. The shortest route in the model is not guaranteed to be the fastest route in reality.

### Comparing UCS with A*

Later in the project, I wanted to compare UCS with another search technique from the course.

UCS already uses the same lowest-cost-first principle as Dijkstra's algorithm.

I chose A* as an additional comparison because it uses an estimate of the remaining cost:

```
f(n) = g(n) + h(n)
```

My reasoning was that the node coordinates and road speeds could provide a lower bound on the remaining travel time.

The heuristic used in the project is:

```
h(n) =
    straight-line distance from n to the goal
    / maximum road speed
```

This is only a valid lower bound when the graph distances and edge costs support it.

I wanted the implementation to check these conditions instead of simply assuming that the heuristic was admissible.

I also wanted the comparison to establish more than agreement between two generated algorithms.

If UCS and A* both contained the same mistake, comparing them with each other would not necessarily find it.

The tests therefore also compare search results with independent shortest-path calculations.

UCS and A* return the same minimum travel times for 1,690 scenario-location pairs under normal and Bayesian road costs.

Both algorithms also match exhaustive simple-path calculations in 750 small-graph cases.

I kept UCS as the normal shortest-path search because the supplied graphs are small and there was no measured runtime problem that required replacing it.

I did not measure whether A* was faster, so I do not claim a performance improvement from this comparison.

---

## 6. Designing the HMM and its role in routing

The HMM was the part where I spent the most time considering how two AI techniques should be combined.

I already had Bayesian probabilities describing the road conditions.

The HMM gives another type of information: the probabilities of Low, Medium and High traffic based on historical observations.

I wanted this information to influence routing without changing the meaning of the Bayesian road conditions.

### Choosing Forward filtering

I wanted to estimate the probability of each hidden traffic state after processing the historical readings.

For that reason, I used the Forward algorithm rather than Viterbi.

Viterbi gives a most likely hidden-state sequence. For this project, I was more interested in the final probability distribution than in reconstructing one particular historical sequence.

I asked ChatGPT to explain the Forward calculation using the course slides and the supplied transition and emission probabilities.

The two main steps are:

```
Prediction:

    predicted(x) =
        sum over y of belief(y) * P(x | y)

Observation update:

    weight(x) =
        predicted(x) * P(observation | x)
```

The weights are then normalized.

The implementation treats the initial distribution as the state associated with the first observation. The first observation is therefore applied directly to the initial probabilities.

A transition is applied before each later observation.

I wanted this convention to be documented because using an additional transition before the first observation would change the calculation.

### Checking the actual probabilities

For road H2 -> N8 in Scenario 2, the observations are:

```
Low, Medium, High, Medium, High
```

The supplied initial probabilities are:

```
Low:       0.50
Medium:    0.35
High:      0.15
```

For the first Low observation, the emission table gives the weights:

```
Low:       0.50 * 0.80 = 0.4000
Medium:    0.35 * 0.15 = 0.0525
High:      0.15 * 0.02 = 0.0030
```

Their sum is 0.4555.

After normalization, the probability of Low traffic becomes approximately 87.8%.

The later observations update the probabilities using both the previous belief and the transition model.

After all five observations, the final probabilities are approximately:

```
Low:        1.01%
Medium:    28.22%
High:      70.77%
```

This example helped me verify that the HMM does more than return the last observed traffic level.

It combines the history and retains uncertainty about the final hidden state.

### Deciding when to process the traffic data

The historical nature of the observations was important for my design.

The supplied files do not specify the time between observations or the time between the last observation and the start of the emergency simulation.

I did not want to introduce a transition every simulated second without knowing what one historical step represents.

I therefore chose to process each road's history before the simulation starts.

The final filtered distribution remains fixed during the run.

For a road without observations, I use the initial probabilities from the corresponding scenario.

I also wanted each directed road to keep its own history. Observations from A -> B are not automatically evidence about B -> A.

The limitation of this approach is that the final belief describes the historical data. It is not guaranteed to describe traffic at the time of a later emergency.

### Avoiding double-counted congestion

One of my main concerns was how to turn the HMM result into useful routing information.

ChatGPT initially suggested multiplying a Bayesian slowdown factor by an HMM traffic multiplier.

I questioned this approach because the assignment already defines the travel times for Open and Congested roads.

The two probability models might be describing overlapping causes of delay.

Multiplying both factors could therefore count the same congestion twice.

Another suggestion was to use the larger of the two factors instead of multiplying them.

I still had a problem with this.

Suppose the Bayesian model is certain that a road is Open. According to the assignment, that road should have its normal travel time.

If the HMM produces a factor of 1.4, taking the maximum would give the road a travel time of 1.4 times normal.

This would change the original meaning of Open.

I therefore decided that the Bayesian model should remain responsible for travel-time estimates, while the HMM should provide a separate routing preference.

This was the clearest way for me to use both models without inventing a joint probability model or a new physical slowdown rule.

### Choosing a separate traffic score

I wanted routes with a large amount of historically high traffic to receive a worse traffic score.

The final score is:

```
Q(route) =
    sum over roads in the route of:

    normal_travel_time * P(High traffic)
```

I chose a duration-weighted score rather than just counting roads with High traffic.

A longer road should contribute more exposure than a short road with the same probability of High traffic.

The score is only a route preference.

It is not extra travel time, and it is not the probability that the route will encounter a blockage.

The arrival calculation still uses the Bayesian travel duration.

### Making traffic affect more than exact ties

The first version of the separate traffic preference considered the HMM score only when two routes had exactly the same travel time.

I questioned how useful this would be in practice.

With fractional travel times, two different routes might rarely have exactly equal costs.

The route comparisons confirmed that there were no exact equal-time shortest-path alternatives in the tested graphs.

I therefore wanted another policy that could prefer a route with lower historical traffic even when it was slightly slower.

At the same time, emergency response time is important, so I did not want traffic exposure to justify an unlimited detour.

The final bounded policy uses:

```
Maximum extra travel time: 5%

Minimum exposure reduction: 10%
```

These settings were fixed before evaluating the scenarios.

The route must fit within the travel allowance and have a sufficiently lower traffic score.

In strict mode, it must also fit within the remaining arrival-deadline budget.

This allows the HMM to influence routing without pretending that the traffic score is a travel-time estimate.

### Extending search for two criteria

The bounded route preference also required a different way of exploring paths.

With ordinary UCS, a slower path to a node can be discarded when a faster path has already been found.

But if I also care about traffic exposure, the slower path could still be useful.

For example:

```
Path A:
    Travel time = 10
    Exposure    = 8

Path B:
    Travel time = 11
    Exposure    = 2
```

Path A is faster, but Path B has lower exposure.

Neither is better in both criteria.

The bounded search therefore keeps multiple useful alternatives at a node and removes a path only when another one has no greater travel time and no greater exposure.

This extends ordinary UCS with a second criterion.

I wanted to keep this separate from the basic UCS implementation so that the original search remained available for comparison.

### What the traffic comparison showed

I wanted to check whether the HMM actually improved the emergency-response results.

The comparison included all three scenarios, both deadline modes, both allocators and three traffic policies.

This produced 36 simulation runs.

The bounded traffic policy changed seven possible endpoint routes in Scenario 3.

One example was N3 -> H1. The alternative route took approximately 2.22% longer but had a traffic exposure score about 44.96% lower.

However, none of the seven changed routes was used by a dispatched responder in the evaluated simulations.

The actual assignments, coverage and response times stayed unchanged.

I decided to keep this result.

Increasing the detour allowance after seeing the results, just to make the HMM have a larger effect, would make the comparison less meaningful.

The experiment shows that the HMM can influence route selection. It does not demonstrate improved emergency-response outcomes for these scenarios.

---

## 7. Generating and checking the final plans

Once the four AI components were connected, I wanted to make sure the program produced exactly what the assignment required.

The final plan contains the responder, incident, selected path and departure time:

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

I wanted the exporter to use the actual committed assignments from the simulation.

It should not calculate another route or make a new assignment decision just to produce the output.

The `time` field represents the absolute departure time.

Arrival and treatment completion are calculated by the simulation and remain available in its internal results.

### Adding an independent validator

I did not want to assume that a generated plan was correct simply because the program had produced it.

A simulation mistake could also appear in the exported plan.

For this reason, I asked for a separate validator that reconstructs the assignment timeline using the original scenario data.

The validator checks:

- Responder capabilities.
- Incident release times.
- Responder availability.
- Starting and destination locations.
- Directed road connections.
- Road restrictions.
- Travel and treatment durations.
- Overlapping assignments.
- Arrival deadlines.

The validator does not call the simulator or allocate responders again.

It shares the Bayesian inference calculation, but independently reconstructs road durations, responder timelines and statistics.

This was important to me because checking a plan with the same scheduling implementation that generated it could miss mistakes shared by both operations.

### A mistake exposed during testing

One concrete implementation mistake appeared in the first version of the validator.

The generated code tried to use:

```python
Responder.location
```

The original input record actually contains:

```python
Responder.start_location
```

Testing the validator against the original scenario records exposed this error.

It was corrected before the final implementation.

This reinforced my reason for requesting tests using the actual input data rather than only examples created for the generated code.

### Distinguishing validity from performance

I also wanted to distinguish a valid plan from a good plan.

A plan can follow all the constraints and still leave several incidents unhandled.

Even an empty plan can satisfy the basic feasibility constraints.

The final statistics therefore describe how the system performed separately from whether the plan passed validation.

I chose the following interpretations:

- An incident is handled when treatment finishes.
- Response time is arrival time minus incident release time.
- Response time includes waiting and travel, but not treatment.
- The average is calculated over handled incidents.
- Unhandled incidents count against the overall deadline percentage.

I wanted the deadline percentage to reflect the complete scenario.

Otherwise, a planner that handled only one incident on time could report 100% on-time performance while ignoring every other emergency.

---

## 8. Making the system easier to run and understand

After connecting the components, I wanted to review the program from the perspective of someone who had not followed the development process.

The final review showed that the original default command still used the all-open routing baseline.

This was useful during the early search tests, but it was not the configuration I wanted for the finished system.

I wanted someone to be able to run the program without first learning all the command-line arguments.

I therefore asked for a scenario menu.

Running:

```console
python run.py
```

allows the user to choose one of the three scenarios.

The main menu uses:

- Bayesian road inference.
- A 20% blockage cutoff.
- HMM Forward filtering.
- Bounded traffic routing with the 5% and 10% settings.
- CP-SAT allocation.
- Strict arrival deadlines.

The output files are saved separately for each scenario.

I also asked for the plan and statistics to be printed in the console.

### Showing the importance of the missed calls

I wanted to know more than the total number of handled incidents.

For example, handling many Low-priority incidents while missing several Critical calls could give a misleading impression if only the total count was shown.

I therefore requested coverage by priority, especially the number of Critical calls handled and the IDs of missed Critical calls.

I also wanted the settings and statistics to be readable without having to understand the internal configuration names.

These changes made it easier to compare the scenarios and understand what the program was doing.

---

## 9. Understanding why incidents were missed

The Scenario 3 results made me want to understand the individual unhandled incidents more clearly.

Knowing that the system handled 13 out of 20 calls was not enough.

I wanted to know why the remaining seven calls were not handled.

Several different situations could explain a missed call:

- No responder has the required skill.
- Qualified responders are busy.
- No usable route exists.
- The available routes would arrive too late.
- A feasible assignment exists, but another incident is selected.

These situations are different and should not be described by one general message.

### Designing the explanation feature

I wanted to record the decisions that the simulator already makes instead of running another planner to explain the results.

The diagnostic feature records capability checks, availability, route existence, estimated arrival and the assignments selected at each decision.

This allows the final explanation to describe how the situation changed over time.

For example, a responder might be busy when an incident is released. They could become available later, but by then the remaining time may be too short.

I also wanted to distinguish incidents that never had an eligible on-time pairing from incidents that had an eligible pairing but were not selected.

This distinction matters when investigating whether the problem comes from routing, availability or competing assignments.

### Avoiding misleading conclusions

I did not want the diagnostic to say an incident was impossible to handle under every possible allocation.

The responder positions and availability are partly determined by earlier assignments.

A different earlier decision could make a later incident reachable.

The diagnostic therefore explains the states reached during the actual simulation.

It does not prove that no other plan could handle the incident.

For each unhandled incident, the summary includes whether an on-time candidate was ever checked and the earliest arrival that was actually calculated.

It does not invent an arrival for a busy or unqualified responder whose route was never checked.

### Checking that explanations do not change the planner

My main requirement was that this addition should not change any planning decisions.

The diagnostics should not perform extra route searches, run the solver again or introduce new simulation events.

A separate comparison checked 48 runs with and without diagnostic recording.

The original assignments, arrival and completion times, event logs, final states and statistics matched.

This confirmed that the feature improved the explanations without changing the measured planning behaviour.

I also asked to simplify the first version of the diagnostic output because it was too detailed for normal use.

The text report now gives a short explanation, the deadline, the best checked arrival and how late it would have been.

The complete decision history is still available separately.

---

## 10. Investigating the scenario results

I wanted to compare the CSP with a simpler allocation method instead of assuming that a more advanced algorithm would always produce better results.

The comparison uses a nearest-responder rule with the same road estimates, routing policy and eligibility conditions.

The nearest method selects available responder-incident pairs according to their travel time, while CP-SAT optimizes the current batch using the priority objectives.

The main strict-deadline results are:

| Scenario | CP-SAT handled | Nearest handled | CP-SAT on time | CP-SAT mean response |
|----------|---------------:|----------------:|---------------:|----------------------:|
| 1        | 6/7            | 5/7             | 85.7%          | 91.1 s                |
| 2        | 11/12          | 11/12           | 91.7%          | 33.3 s                |
| 3        | 13/20          | 15/20           | 65.0%          | 607.9 s               |

### Why did the simpler method perform better in Scenario 3?

This result was particularly interesting to me.

I had chosen CP-SAT because it considers competing assignments together. I wanted to understand why the nearest-responder method could still handle more incidents.

The comparison showed that an early equal-cost choice involved responders with different capabilities.

The two allocation methods selected different responders for the first-aid call I4.

This affected where those responders were located when later medical calls appeared.

The solver was optimizing the current assignment, but it had no objective for preserving useful skills or positioning responders for future incidents.

This is a limitation of my allocation design, not necessarily a mistake in the CP-SAT implementation.

An optimal current decision does not guarantee an optimal complete simulation.

I chose to keep and explain the result rather than change the objective until CP-SAT happened to outperform the baseline.

### Comparing strict and late responses

I also wanted to understand how much the strict-deadline rule influenced coverage.

With late responses allowed, CP-SAT handled all incidents in all three scenarios.

However, it missed:

- 2 deadlines in Scenario 1.
- 2 deadlines in Scenario 2.
- 9 deadlines in Scenario 3.

In Scenario 3, allowing late responses resulted in more completed incidents but fewer on-time arrivals.

Once a responder accepts a late incident, they can be occupied when another incident appears.

This experiment supported my decision to keep handled status and deadline status separate.

It also showed that maximizing the number of completed incidents is not the same objective as maximizing the number reached on time.

I kept strict deadlines as the normal configuration.

---

## 11. My proposed Critical fallback policy

After investigating the Scenario 3 results, I started thinking about whether the same road-risk threshold should apply to every incident.

My idea was that a Critical emergency might justify considering a higher-risk route when no acceptable normal route could provide an on-time response.

However, I did not want the system to choose a risky shortcut simply because it saved a few seconds.

If a normal route could achieve the required response, I wanted that route to remain preferable.

I discussed this idea with ChatGPT before making any implementation changes.

### A problem with considering incidents separately

The first proposed design checked each Critical incident individually.

If a normal on-time option existed for an incident, all fallback options for that incident would be removed.

I noticed a problem with this approach.

Suppose there are two Critical incidents, A and B:

| Assignment | Normal route | Higher-risk route |
|------------|--------------|-------------------|
| R1 -> A    | Available    | Not needed        |
| R1 -> B    | Available    | Not needed        |
| R2 -> A    | Unavailable  | Available         |

If incident A is considered separately, its fallback option is removed because R1 can reach it normally.

However, R1 is also the only normal option for incident B.

The solver can therefore handle only one of the incidents.

I realized that the fallback decision should consider the allocation as a whole.

If R2 can take A using a fallback route, R1 can handle B. Both incidents then receive an estimated on-time response.

This is the reason I wanted to compare complete allocation batches rather than decide about higher-risk roads independently for each incident.

### Comparing allocations instead of individual routes

My revised idea was to compare two allocations for exactly the same current situation:

1. An allocation using only normal road options.
2. An allocation that also permits Critical fallback options.

A fallback should only be considered when it produces a demonstrated increase in the number of Critical incidents that can be reached on time.

This prevents higher-risk roads from being selected only because they offer a shorter estimated journey.

The comparison would also need to distinguish a proven allocation improvement from a solver result that had not finished within its time limit.

### Considering the effect on other priorities

Another question was whether a fallback should be allowed to reduce lower-priority coverage.

ChatGPT suggested protecting the number of High, Medium and Low incidents assigned in the normal allocation.

I questioned whether that matched the priority order I had already chosen for the CSP.

Consider:

```
Normal allocation:
    1 Critical
    2 High

Fallback allocation:
    2 Critical
    1 High
```

My current objective places Critical coverage before High coverage.

A rule requiring High coverage to remain unchanged would reject the second allocation.

I realized that these are two different policies.

One gives absolute preference to Critical coverage. The other allows an additional Critical assignment only when lower-priority coverage is protected.

I wanted this choice to remain explicit rather than introduce a new constraint without considering its meaning.

### Considering whole-route risk

I also questioned using only the highest blockage probability on a route to compare risk.

A route with several moderately risky roads may have a greater chance of encountering a blockage than a route with one road that has a higher individual probability.

This means the worst-edge probability does not fully describe route risk.

The existing probability bounds are useful for showing this uncertainty, but the project still has no joint model of road failures.

Another limitation is that the simulation assumes the selected route can be followed.

A fallback road could have a high probability of being blocked, and its estimated on-time arrival assumes that it is passable.

Counting more modeled on-time responses would therefore not be enough to establish that the fallback policy is better.

### Why I left this feature unimplemented

I decided not to include Critical fallback in the submitted planner.

The idea would require changes to candidate generation, allocation, validation and reporting.

More importantly, it would introduce another risk policy that needs careful evaluation.

I preferred to complete and validate the current system rather than increase the incident count by accepting risk that the simulation could not evaluate properly.

The current system therefore continues to apply the same configurable road cutoff to every incident priority.

Critical fallback remains a proposed extension.

---

## 12. Testing the system

Throughout the project, I wanted to check both the individual AI techniques and the complete simulation.

I asked for small tests with independently known results before combining the components.

The final test suite contains 175 passing tests.

Some of the most important checks are:

- Bayesian probabilities compared with worked calculations.
- Forward filtering compared with explicit hidden-state sequence enumeration.
- UCS and A* compared with independent shortest-path calculations.
- Small CSP models compared with every possible assignment.
- Simulation tests for release times, busy responders, arrivals and treatment completion.
- Deadline and capability checks.
- Exported plans reconstructed using the original scenario data.
- Comparisons with and without diagnostic recording.

I wanted these tests to check the reasoning behind the implementation, not just whether the functions returned a result.

For example, comparing Forward filtering with all possible hidden-state sequences gives another way of checking the probability calculation.

Similarly, comparing the allocation model with exhaustive enumeration on small examples makes it possible to check whether the constraints and objective produce the intended assignment.

The detailed test cases and results are documented in [TESTING.md](TESTING.md).

### What the tests establish

The tests support the correctness of the implemented calculations and planning rules for the cases examined.

However, they do not establish that the planning policy is optimal over an entire scenario.

They also do not establish that the estimated road conditions match real road conditions.

The separate plan validator checks feasibility using the original scenario inputs and the chosen travel-time assumptions.

I wanted to keep these limitations clear because it would be easy to overstate what a passing test suite proves.

---

## 13. What I would improve next

The current system provides a complete implementation of the four required AI techniques, but there are still several improvements I would like to investigate.

### Simulating road failures

The most important limitation is that the simulation assumes responders can follow their selected routes.

I would like to introduce actual road-condition outcomes and allow a responder to discover that a planned road is blocked.

The responder could then lose time, update their information and search for another route.

This would make it possible to investigate whether a routing policy still performs well when the estimated road conditions differ from the actual conditions.

It would also make the road blockage probabilities more meaningful during execution.

### Evaluating Critical fallback

I would like to return to my Critical fallback idea once road failures and recovery can be evaluated more realistically.

I would compare the original road policy with the fallback policy and report both the improvement in Critical coverage and the additional risk accepted.

I would not judge the feature only by the number of incidents handled.

### Planning more than one assignment

The current CSP assigns immediate jobs.

It does not consider whether waiting for a busy responder might lead to a better sequence of assignments.

I would like to investigate a scheduling model that considers several already known incidents over a longer planning horizon.

This could help preserve responders with scarce capabilities and avoid assignments that leave the wrong responder in the wrong place later.

However, it would require a more complicated model of time and availability.

### Modeling what happens after treatment

I also started thinking about what responders should do after finishing treatment.

The current simulation makes them available at the incident location.

In practice, an ambulance may need to transport a patient to a hospital before it becomes available again.

Other responders might need to return to their station or remain near the incident.

I would like to include these additional journeys and their durations in the simulation.

I would also compare the effect of returning responders to their stations with leaving them at their current locations.

The Scenario 3 results already show why responder location matters for later emergencies.

None of these extensions is implemented in the submitted version.

---

## 14. Reflection on my use of the LLM

I used the LLM throughout the project, but I wanted to remain responsible for the system's design and the decisions that determine its behaviour.

The LLM was useful for explaining the mathematical details, generating Python implementations, developing tests and investigating problems.

My role was to decide what the system should do, which assumptions were reasonable and which proposed approaches I wanted to keep.

Several important decisions came from questions I raised during development.

I wanted Bayesian road conditions and HMM traffic levels to remain separate because they describe different types of information.

I wanted to keep the full Bayesian distribution instead of treating the most likely road condition as certain.

I wanted the simulation to reveal incidents over time rather than allow the allocator to use future information.

I questioned whether minimizing response time alone would give the solver a reason to handle incidents.

I chose to maximize coverage by priority before minimizing response time, and I rejected an additional deadline-ranking objective.

I also questioned whether combining the Bayesian and HMM slowdown factors would count congestion twice. This led to the separate traffic-exposure policy.

When the first HMM integration was limited to exact-time ties, I wanted a way for historical traffic to have a more meaningful effect without allowing unlimited detours.

Later, I proposed the Critical fallback idea and identified the problem of checking incidents individually when they compete for the same responders.

I decided to leave that feature for future work because I did not think it had been evaluated sufficiently.

I also wanted the project to explain its weaker results rather than hide them. This was why I retained the nearest-responder comparison and added explanations for unhandled calls.

The collaboration helped me turn these design decisions into a working implementation and examine their consequences.

I learned that an LLM can provide a convincing explanation while still making an incorrect assumption about the data or the problem.

I also learned that an algorithm can be implemented correctly without producing the best result for the complete system.

The Scenario 3 comparison was a good example. CP-SAT can optimize the current allocation correctly, but a different earlier assignment can still lead to better coverage later.

The most important part of the project for me was understanding these differences between the mathematical methods, the planning policies built around them and the results observed during simulation.


---

## Original first substantive LLM prompt

The following is my original first substantive prompt, reproduced without rewriting.

> I've attached my AI practicum assignment, the scenarios and the course slides.
>
> From what I understand, we need to build a system that assigns emergency responders to incidents and finds suitable routes, while taking into account deadlines, responder availability and uncertain road conditions.
>
> We need to combine search, CSPs, Bayesian reasoning and HMMs to do this. Before starting the implementation, I want to figure out how these components should work together and how to structure the project.
>
> Since the assignment is open-ended, I'd like to discuss the possible approaches and important design decisions first. Use the course slides as the main reference, but feel free to suggest alternatives and point out problems with my approach.
>
> The goal is to build a working system that I can fully understand, test and defend afterwards.
