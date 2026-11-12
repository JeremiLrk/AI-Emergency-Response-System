# My design decisions and use of the LLM

## Current version and report

The current suite has **175 tests**. The lower test counts below describe earlier development stages, not the current program. The report uses the same Bayesian and HMM examples, .20 road cutoff, .05/.10 bounded-routing settings, strict/late objective order and scenario results as the code and saved comparisons. UCS remains the normal search; A* is implemented and tested for comparison, with no measured speedup claimed.

ChatGPT helped explore and explain the design, while Codex helped generate, document, debug and test the implementation. I steered the work by reviewing examples and changing or rejecting suggestions. A correction to a proposed design is recorded as a design correction, without implying that the rejected proposal was implemented.


I used ChatGPT to explore the design and Codex to help implement, document and test the system. I asked for explanations before implementing each major component, questioned the assumptions, and chose which proposals to keep. The LLM contributed code and test cases. I used worked examples, scenario comparisons and a separate check that works through the plan from the original data to examine their behaviour. The exact first main prompt appears at the end.

The four methods have different roles in the design. The Bayesian calculation updates the chances of each road condition using reports that can be wrong. The HMM combines a sequence of noisy traffic readings. Search finds a path using the resulting road estimates and route preferences. CP-SAT chooses who goes to each call while following the assignment rules. Keeping those roles separate makes it possible to test both the calculations and how they affect the final decisions.

## Questions and corrections that shaped the project

This table summarizes the decisions and corrections made during development. It distinguishes changes to the implementation from proposals that stayed in discussion.

| Proposal or issue | What I questioned or corrected | What happened |
| --- | --- | --- |
| Road conditions and HMM traffic were mixed together in the design. | I asked to inspect the actual files and pointed out that the HMM states are Low, Medium and High, separately from Open, Congested and Blocked. I also clarified that the traffic readings are historical. | The two probability models use their own state labels and evidence. Historical readings are processed before simulation. |
| Routing could select the most likely road condition and act as if it were certain. | I asked to keep all road-state probabilities and consider the safety implications of a route. I also wanted the blockage cutoff configurable because a strict cutoff could make many calls unreachable. | Full distributions are retained. Road filtering is an explicit policy with a configurable cutoff and reported risk bounds. |
| A missed deadline could cause the system to abandon an incident. | I questioned whether the assignment required that behaviour and asked to separate deadline results from work status. | Strict mode remains the main configuration, with a separate allow-late experiment that can complete late calls. |
| A response-time objective could favour sending nobody. | I asked how the solver would reward actually handling emergencies. | Coverage by priority is optimized before response time. |
| Deadline ranking was proposed before response-time minimization. | I argued that an earlier deadline does not justify a longer response when both choices arrive on time. | The implemented objective uses the number of calls handled by priority, then the number reached on time in late mode, then response time. |
| HMM and Bayesian slowdowns could be multiplied or combined by taking their maximum. | I pointed to the assignment's normal Open time and 1.5-times Congested time, and questioned whether another factor would count congestion twice. | Bayesian road conditions determine travel estimates. HMM traffic provides a separate exposure preference. |
| HMM exposure was initially proposed only for exact-time ties. | I questioned whether that would affect any route in the three scenarios. | A bounded detour policy was also evaluated with fixed settings. It changed some possible routes, while actual dispatch outcomes stayed the same. |
| A benchmark could be improved by adjusting parameters after seeing the results. | I asked to keep the Scenario 3 CSP disadvantage and the unchanged HMM dispatch results documented. | Those results were retained and explained. |
| Normal execution required several flags and the statistics were hard to interpret. | I asked for a scenario menu, console output, a clear count of Critical calls handled and readable settings. | The no-argument menu runs the full pipeline. The report shows the number of calls handled by priority and plain-language settings. |
| Critical fallback was checked separately for each incident. | I pointed out that two Critical calls can compete for the same normal responder, while another responder could take one through a fallback route. | The proposed comparison moved to the allocation level. I decided to leave implementation for later. |
| The fallback proposal protected the number of lower-priority calls handled and used worst-edge risk. | I questioned whether protecting all those lower-priority counts fits the existing Critical-first objective and noted that worst-edge probability does not describe whole-route blockage risk. | These trade-offs remain explicit open design choices for the proposed extension. |

## 1. Start from the supplied data

I chose Python and OR-Tools CP-SAT for allocation, with uniform-cost search implemented directly in Python for routing. I wanted separate modules for probability calculations, routing, assignment and simulation so that I could follow how each decision was made. I also wanted small tests before connecting the components.

Before implementation, I asked for the actual scenario files to be inspected. I identified a distinction that mattered throughout the project. Bayesian road conditions are Open, Congested and Blocked. The HMM's traffic states are Low, Medium and High. I also clarified that the traffic observations are historical and should be processed before the simulation.

The scenario README resolved the units and timing. Distances are metres, speeds are metres per second, and simulation times are seconds. Weather belongs to the reported road direction. The three real scenarios were checked alongside synthetic examples.

The first implementation added typed loaders, a graph adapter, UCS implemented directly in Python and tests. I kept open the questions that the files could not resolve, including the age and spacing of historical readings and the finish location of an initially busy responder. The chosen assumption is that an initially busy unit becomes available at its supplied start node. [Design decisions](DESIGN.md)

## 2. Preserve uncertainty in Bayesian reasoning

I asked for a step-by-step explanation using the course slides and actual probability tables before approving this module. The Scenario 1 N1 → N2 example produced weights .00012, .00384 and .00441, divided by their total of .00837 so the three probabilities add up to one. After reviewing the calculation, I asked to keep all three probabilities rather than treat the most likely road condition as certain.

The model starts with road probabilities based on the weather. It multiplies them by how likely each report would be for each possible road condition, then divides by the total so the probabilities add up to one. Known weather is local to the road. If weather is unknown, the model averages over the possible weather conditions using their supplied probabilities. Missing sources contribute no evidence. Each road direction has its own reports, and duplicate source reports or conflicting weather are rejected.

I accepted the proposed separation between calculating road probabilities and choosing routes. The probability calculation returns all three road probabilities. Routing applies an edge blockage cutoff and estimates travel time assuming the road can be used. The function and command-line mode require a cutoff, while the menu uses the .20 setting used in evaluation. The assignment supplies no cutoff shown to be safe in real conditions.

The design also reports a range for route blockage probability using a lower bound from the riskiest road and an upper bound from the sum of the road probabilities, capped at 100%. This avoids assuming that road failures are independent. The assumption is that once we know the actual road condition, one source's report gives no extra clue about another source's report. That is what permits multiplying the chances of their reports. The assumptions still matter. Reports that depend on each other can make the Bayesian result too confident, and a route made of individually accepted roads can have more blockage risk than the cutoff for each road.

I requested explanations of parameters, preconditions and postconditions, together with tests and decision notes. This stage passed **39 tests**, including **22 additions** and **845 extra Bayesian graph pair comparisons**. At cutoff .20, Scenario 2 leaves 60 of 132 ordered pairs of distinct nodes reachable. Threshold sensitivity was examined, and a faster route could still be riskier than a slower one. At this stage the evidence concerned routing. Dispatch, HMM integration and full-plan evaluation followed later.

## 3. Model time and availability explicitly

I reviewed the event-based simulation design before asking for code. I agreed that simultaneous events should be processed together and that the controller should be separate from the future allocator. I also questioned automatically abandoning a call once its deadline was missed. I chose strict arrival deadlines for the main configuration and an allow-late experiment, with work status separate from deadline outcome.

This means a call can finish treatment and still be marked late. A call left unhandled has a recorded closure reason. A committed job runs through travel and treatment, and a responder's next route starts where the previous treatment finished.

The generated implementation used a private event queue, frozen current-state views, validation of a complete dispatch batch before commitment, initial busy periods, changing locations, zero-duration events, logs and scripted assignments. Scripts supply responder and incident IDs, while the controller builds and checks current routes and timings. The assignment code receives only calls that have already appeared. Arbitrary Python callbacks could still read external files, so the interface is a guard against accidental lookahead.

This development stage passed **72 tests**, preserving 39 and adding 33. They covered release boundaries, earlier saved views that stay unchanged, rejection of invalid batches, late outcomes, scripts and CLI, all three incident streams with no dispatches, and a separate check of four Scenario 1 assignments using the original data.

The sample script deliberately handles four of seven calls to test the execution rules. Each timestamp is consumed once, while callbacks can trigger successive zero-duration jobs. Float times keep nearby releases separate. Positive durations too small to advance a large clock raise an error. Rerouting, interruption, actual road failures, CP-SAT, HMM and final files were outside this development stage.

## 4. Give the solver a reason to handle emergencies

I raised the concern that minimizing response time alone could reward leaving calls unassigned. I accepted yes-or-no assignment choices and rules, then asked for the number of calls handled by priority to come before response-time minimization.

I also rejected the proposed deadline-ranking stage. If both calls can be reached on time, an earlier deadline alone does not justify choosing a much longer response. The implemented order is:

1. Maximize assignments for Critical, then High, Medium and Low.
2. When late responses are permitted, maximize on-time counts in that order while keeping the assignment counts already achieved.
3. Minimize total predicted response time.

The part that assigns responders receives a view of the current time, responders and known calls and returns assignment IDs. The simulator builds the candidate routes and independently checks the returned batch. The yes-or-no choices are added together to enforce the rules, following the CP-SAT example in the course. The solver handles one goal at a time. It only locks in a result once it has proved that result is the best possible for that goal. This avoids guessing numeric weights for each priority. Response costs use rounded-up integer milliseconds, while the simulation keeps the full time values.

The implementation reports solver statuses and limits, retains a previous valid solution when appropriate, and raises explicit errors for invalid models. It has no extra urgency, deadline-slack or waiting-age rank. A rule that picks the nearest responder who meets the requirements was added as a comparison under the same road and deadline rules. Script and route modes remain available. OR-Tools 9.15.6755 is fixed to that version in requirements.txt and installed in a project environment.

This stage passed **102 tests**, keeping 72 and adding 30. Tests checked the objective order, constraints, actual responder conflicts, small examples checked by trying every possible assignment, solver statuses and time limits, plan checks, views of the current situation and command-line behaviour. Two combinations that previously failed became valid automatic command-line modes, so those tests were updated for the changed interface.

The results challenged the expectation that a locally optimal solver would always handle more calls. With strict deadlines and cutoff .20, CP-SAT handled 6/7 versus nearest 5/7 in Scenario 1, tied at 11/12 in Scenario 2, and handled 13/20 versus nearest 15/20 in Scenario 3. Equal-cost early assignments left responders with different capabilities in different places for later medical calls. All recorded local objectives were proved, and repeat runs reproduced the saved assignments and metrics for the pinned setup.

I chose to keep and explain that result. The part that assigns responders only optimizes the current decision. There is no objective for preserving skills that few responders have, waiting age or route safety. Rounding, tie choices, Python overhead beyond a hard time limit and uncertain travel estimates also limit what a solver result establishes. [Tests and results](TESTING.md) · [Allocation comparison](results/allocation_comparison.json)

## 5. Give historical traffic a separate routing role

I questioned the proposed multiplication or maximum of Bayesian and HMM slowdown factors. The assignment gives Open roads normal travel time and Congested roads 1.5 times normal. Adding another factor could count congestion twice. I chose to keep Bayesian conditions responsible for travel estimates and use HMM traffic as a separate route preference.

Forward filtering follows HMM slides 17–23. The implementation treats the supplied starting probabilities as the state for the first observation, applies that observation, then repeats predicting the next traffic level, using the next reading to update that prediction, and making the probabilities add up to one. Each road direction keeps its three probabilities for Low, Medium and High. Missing history uses the scenario's starting probabilities, which are different in Scenario 2. Reverse-road evidence is kept separate. Unknown historical age and time between readings give no basis for adding one transition per simulation second.

I also raised the concern that exact-time tie-breaking might have little effect in the supplied data. I approved both the strict shortest-path tie policy and a configurable bounded detour policy. The score adds normal travel seconds multiplied by P(High) along the route. The tie policy compares time first and exposure second. The bounded policy keeps useful alternatives at each node and compares exposure, then time, within its allowance.

This search extends ordinary UCS. It has a 100,000-label guard that raises an error when exceeded. Plain Bayesian-only routing remains available. The traffic exposure score stays separate from the travel seconds used for arrival, treatment and availability. Strict mode also checks the remaining deadline budget. In late mode a detour can turn an otherwise on-time pairing into a late one. CP-SAT receives one selected route per responder–incident pair.

The evaluation used **5% maximum extra travel** and **10% minimum exposure reduction**, fixed before observing the results. This stage passed **121 tests**, retaining 102 and adding 19. Checks included the worked probabilities, trying all possible hidden-state sequences in small examples, missing histories, separate road directions, invalid input, exact and near ties, detour search checked against every path in small graphs, timing and CLI.

The 36-run comparison covered all scenarios, both allocators and both deadline modes under three traffic policies. Neither HMM policy changed the actual committed routes, assignments, handled counts, deadline counts or mean responses. Bounded routing changed seven of 676 reachable endpoint pairs in Scenario 3 and none in Scenarios 1 and 2. Exact tie routing changed none. The N3 → H1 alternative reduced exposure by 44.96% for 2.22% more estimated time, but was never dispatched.

I kept those settings and reported the lack of improvement in the actual assignments. Live traffic and checks against real traffic conditions were unavailable, and the historical score cannot establish actual road safety. Actual failures and recovery remain outside the simulation. [Traffic comparison](results/traffic_comparison.json)

## 6. Export the specified files and check them independently

I asked for the assignment's output requirements to be checked before implementing export. Sections 3, 5 and 8 and the scenario README specify the plan rows as responder_id, incident_id, path and time. Time is dispatch start. The statistics requirements ask for handled calls, responders used, average response and deadline percentage, with an explanation of unhandled work.

I requested export from the existing simulation result and a separate validator against original inputs. The exporter copies recorded assignments and uses the existing summary. It keeps the required plan fields. Explicit runs save in the working directory unless output-dir is supplied, comparison runs use separate folders, and route inspection writes no assignment files. The later scenario menu saves under results/menu/ScenarioN/ and prints both files.

The separate plan checker uses the tested Bayesian calculation, then works out road times, responder readiness and locations, travel, treatment, deadlines and statistics from the original data. It does not call the simulator, search, graph builder, allocator or summary function. Export compares the checker's travel, arrival, completion and statistics against the original run before writing.

The first validator test run caught generated code using Responder.location on an input record that stores start_location. The field was corrected before deployment. This is a concrete example of why I requested checks against original scenario records.

I wanted the results to show both whether a plan follows the rules and how well it handles calls. A partial or empty plan can be valid. Late-mode validity applies to that relaxed rule and still reports missed deadlines. Unhandled calls count against the all-incident deadline percentage and stay out of the response mean. Empty means show N/A. Invalid plans receive errors instead of performance scores.

This development stage passed **145 tests**, retaining 121 and adding 24. They covered schema and JSON errors, IDs, skills, releases, readiness, overlap, treatment, location, directed edges, Bayesian duration and cutoff, deadlines, empty plans, start times, corruption, CLI files and validator exits. Export tests ran 18 scenario, route-policy and deadline-mode combinations. Existing CLI tests were given isolated output folders while keeping their behavioural assertions.

Six saved strict and late runs passed the separate plan check and matched the simulation's assignments and statistics. Strict CP-SAT handled 6/7, 11/12 and 13/20. Allow-late handled all incidents but missed 2, 2 and 9 deadlines. I retained the existing HMM and Scenario 3 findings. [Saved plan checks](results/plan_export_validation.json)

## 7. Review results before adding more complexity

I asked for a final review of the code, tests and assignment requirements. The audit exposed that the original default run used the optimistic all-open routing baseline. I requested a console scenario menu because the flags made normal execution difficult to follow. The menu now runs the full pipeline with the same settings for all three scenarios. I also asked for console output, counts of Critical calls handled and simpler statistics and documentation.

The final code review reran the 145 tests and added three tests to catch specific problems if they happen again, bringing the total to **148**. They exercise the real menu across all scenarios, invalid choices and clean exit, and a total route time too large for Python to store as a finite number. Existing export tests now also check Critical totals, the all-handled answer and missed Critical IDs.

UCS now raises an explicit overflow error where an extremely large path sum previously could appear unreachable. The supplied scenarios are far below that limit. Two comments that described simulation as future work were corrected. TESTING.md starts with a current test guide and keeps the earlier development stages as history.

All 148 tests passed and the dependency check passed. We did not measure what percentage of code lines or possible code paths the tests ran. Future claims about safety, live traffic, recovery or whole-scenario optimality need additional evidence. Remaining submission work includes the report, repository publication and access, and defence preparation.

## 8. Proposed Critical fallback

I suggested considering a higher road cutoff for Critical calls when the normal policy cannot reach them on time, while still preferring a normal on-time route. The first design checked this separately for each incident. I pointed out that two Critical calls can depend on the same responder for their normal routes. Offering another responder a fallback could let both calls be reached.

The revised proposal compares normal-only and expanded allocations on the same view of the current situation. Fallback would require a demonstrated increase in the number of Critical calls handled. I also questioned a rule that protects the number of lower-priority calls handled because they would deliberately change the existing Critical-first objective. The choice between preserving that priority order and a policy that also protects lower-priority calls remains open.

I noted that the highest edge blockage probability does not measure the chance of encountering any blockage over the whole route. A predicted arrival still assumes the route can be used. I decided to leave this for later and focus on checking the current program, making its results repeatable, and meeting the deadline. The current planner continues to apply its selected road cutoff to every priority. Setting aside busy responders for later calls and the other proposed planning changes also remain future work. [Proposed design](DESIGN.md#10-proposed-ideas-that-are-not-implemented)

## 9. Explanations for unhandled calls

I chose to add explanations to help understand and defend the results. I required them to remain strictly diagnostic: no changes to routing, CP-SAT decisions, timing, deadlines or existing statistics. I specifically asked to reuse the simulator's eligibility checks and decision snapshots, rather than run a second planner. I also asked to distinguish a call with no checked on-time candidate from one that had a candidate but lost a competing assignment.

The implementation records the existing skill, availability, route and arrival checks and the actual selected batch. Busy responders have no calculated route or arrival. The summary reports whether an eligible on-time candidate was ever checked and the earliest arrival actually calculated. Full histories remain available in the result and explicit CLI JSON; statistics.txt gets a shorter explanation. The required plan format stays the same. I required the wording to avoid claiming that every possible allocation would fail: our current assignments affect later responder positions and availability.

The new tests cover changing reasons, competing calls, missing skills and roads, no responders, late-only candidates, deadlines before release, repeated same-time decisions and solver budget exhaustion. All 160 tests passed. A separate before/after check compared 48 runs across the three scenarios, deadline modes, allocators and routing policies. All original assignments, times, event logs, final states and statistics matched exactly. This adds explanations, not better coverage, guaranteed arrivals or a proof of whole-scenario optimality.

I found the first diagnostic report too difficult to read and asked for simpler wording and a cleaner layout. The text now gives a short reason, deadline, best arrival and how late it would be for each call. Detailed histories remain available separately. This changes presentation only.

## 10. Compare search methods from the course

I asked whether we had compared A* or Dijkstra with our search. UCS uses the same lowest-cost-first principle as Dijkstra. I chose A* from the course for an additional comparison and asked for thorough tests of both algorithms.

A* now follows f = g + h, using straight-line distance divided by maximum road speed as its checked lower bound. The code checks the geometry and graph costs that make this estimate valid. The two all-pairs checks compare A* with UCS across all three scenarios under normal and Bayesian costs. Independent enumeration of every simple path on small graphs checks both algorithms rather than assuming agreement proves correctness. Tests also cover zero-cost cycles, unreachable routes, stale entries, invalid heuristics, overflow and reopening nodes. The final suite passes 175 tests. UCS remains the normal planner; no improvement in response counts or runtime is claimed from this testing change.

## 11. Final report review and proposed next steps

I wanted the report to explain the project without requiring the reader to see the chat. I simplified the wording, kept formulas connected to the course, and separated the inference methods from our own planning choices. The report explains the accepted and rejected suggestions, tests, results and limitations. Its original first substantive prompt matches the prompt preserved below, apart from layout whitespace.

The final review checked the report against the source, the saved comparisons and the Markdown guides. The Bayesian N1→N2 example and Scenario 2 H2→N8 traffic example match recalculated probabilities. Strict CSP handled 6/7, 11/12 and 13/20, with means 91.1, 33.3 and 607.9 seconds. Nearest handled 5/7, 11/12 and 15/20. Allow-late CSP handled all calls but missed 2, 2 and 9 deadlines. The HMM changed seven possible endpoint routes in Scenario 3 but none of the actual committed journeys. These are estimated simulation outcomes, not measured real-world arrivals.

My next-step ideas are to simulate discovering blocked roads and rerouting, test the proposed Critical fallback while reporting coverage and risk together, and consider what happens after treatment. An ambulance may need to take a patient to hospital and remain busy through handover. Other units might return to their station, or remain near the last incident. These trips and availability rules would need their own design and tests. The present code frees responders at the incident when treatment finishes; it does not implement hospital transport, handover or station return. Waiting for a busy responder to serve a second call at the same location also remains a proposal.

Testing exposed a generated validator field mistake, using Responder.location instead of start_location, which was corrected. That remains a concrete debugging example even if the shorter report focuses on the other design corrections. None of these notes changes the algorithms or presents a proposed extension as an implemented feature.

## Exact first substantive prompt

```text
I've attached my AI practicum assignment, the scenarios and the course slides.

From what I understand, we need to build a system that assigns emergency responders to incidents and finds suitable routes, while taking into account deadlines, responder availability and uncertain road conditions.

We need to combine search, CSPs, Bayesian reasoning and HMMs to do this. Before starting the implementation, I want to figure out how these components should work together and how to structure the project.

Since the assignment is open-ended, I'd like to discuss the possible approaches and important design decisions first. Use the course slides as the main reference, but feel free to suggest alternatives and point out problems with my approach.

The goal is to build a working system that I can fully understand, test and defend afterwards.
```
