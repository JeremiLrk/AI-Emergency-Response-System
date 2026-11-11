# What we asked the LLM and what we changed

We used ChatGPT to discuss the design and Codex to work on the code, tests and documentation. The first substantive prompt is quoted at the end. The assistant also read the pasted earlier chat to recover the design context. Use the actual tool and model names from the app history in the report, since the code does not record model versions.

## 1. Start with the real inputs and search

We agreed on Python, handwritten uniform-cost search (UCS), separate probability, routing and allocation modules, OR-Tools CP-SAT later, and tests at each step. We also agreed that the allocator only sees released calls and a committed job runs to completion.

The first discussion mixed up the HMM's traffic levels and the Bayesian road conditions. The traffic levels are Low, Medium and High. Road conditions are Open, Congested and Blocked. The scenario README confirms that the traffic readings are historical and available before the simulation.

The assistant initially looked for the archive under the English Desktop path. The user pointed to the redirected OneDrive/Bureaublad repository, where the scenarios had already been extracted. This let us check all three real scenarios as well as small test inputs. The scenario README supplied the units and explained that weather is local to a directed road.

The first code checkpoint added typed loaders, a graph adapter and tests, and kept the handwritten UCS foundation. Bayesian inference, dispatch and the other AI components followed later. Open questions at this point included how to use traffic without counting congestion twice, what location to use for initially busy responders, and how much confidence to put in estimated arrivals. The files have no time spacing for traffic readings and give no separate finish location for the initial busy job. [Design decisions](DESIGN.md)

## 2. Keep all three Bayesian probabilities

The user asked for an explanation before implementation. The assistant checked the course slides and scenario tables. In the Scenario 1 N1 → N2 example, the weights were .00012, .00384 and .00441, and the sum used to normalize them was .00837. The user accepted the calculation and asked to keep the full distribution rather than act as if the most likely state were certain. Implementation followed that review.

We multiply the prior by the available report likelihoods, use the road's known local weather, and sum over weather when it is unknown. Missing sources contribute no evidence. Each direction keeps its own evidence. The loader rejects duplicate reports and conflicting weather. Bayesian inference produces probabilities for every road, and the route policy uses them separately.

The assistant proposed an edge cutoff and a travel estimate conditional on the road being passable. This replaced automatic conversion to a single most likely road state (MAP). The API and explicit Bayesian CLI take a chosen cutoff. .20 was the evaluation setting and later became the menu setting. The assignment does not give a safe cutoff. We kept UCS and report a route blockage range using a union bound, without assuming independent road failures.

The user requested parameters, preconditions, postconditions, tests and updated design and reflection notes. The checkpoint passed **39 tests**, including **22 new tests** and **845 extra Bayesian graph pair comparisons**. At .20, Scenario 2 has only 60 of 132 ordered pairs of distinct nodes reachable. We measured how changing the cutoff affects routing. A faster accepted route can be riskier, several accepted roads can create route risk above the cutoff, and copied reports can make the model overconfident. The estimated travel time assumes passability. This checkpoint evaluated routing without dispatch metrics, ground-truth road checks, HMM, allocation or simulation.

## 3. Simulate releases, travel and treatment

The user asked for a design explanation first. We used actual Scenario 1 releases, responder readiness and Bayesian travel estimates to separate assignment rules from our event queue choices. The user approved handling simultaneous events together and keeping the simulator separate from the future CSP. They also corrected the idea that a missed deadline must always end the call. We kept strict deadlines as the main policy and added a late experiment.

Work status and deadline status are separate. A call can finish treatment and still have missed its deadline. Strict mode and end-of-run closure record separate reasons for leaving work unassigned.

We implemented a private event engine, frozen views of current work and candidates, whole-batch checks before committing, uninterrupted travel and treatment, changing locations, starting busy times, same-time zero-duration events, logs, scripts and CLI support. Scripts give IDs. The engine finds routes and times using UCS. The checkpoint did not yet include CSP or greedy allocation. Callbacks receive current inputs only, although arbitrary Python code could still read scenario files directly.

This stage passed **72 tests**, keeping 39 and adding 33. They covered timing boundaries, views that cannot be edited, no future calls in the snapshot, rejection of a whole invalid batch, late outcomes, scripts and CLI, all three streams with no dispatches, and independent replay of four Scenario 1 assignments.

The sample script handles four of seven calls on purpose to test the engine. It consumes each timestamp once, while a custom callback can chain zero-duration jobs. Float times keep distinct releases separate, but rounding can still matter at a boundary. The simulator rejects positive time steps that cannot advance the clock. Initially busy responders become free at their supplied start node. At this checkpoint, rerouting, interrupted jobs, road failures, HMM, CP-SAT and final outputs were still deferred. Estimated deadline success is a model result.

## 4. Choose coverage before response time

The assistant proposed yes-or-no assignment variables, leaving calls unassigned when needed, priority counts in order, deadline ranking and response time. The user accepted CP-SAT and the assignment rules but rejected deadline ranking before response time. When both calls are feasible, an earlier deadline alone does not justify a longer response. The approved order is:

1. Maximize Critical, High, Medium and Low coverage in order.
2. In allow-late mode, maximize on-time counts by priority after fixing coverage.
3. Minimize estimated response time.

There is no extra earliest-deadline, slack or urgency rank. The allocator receives only a `DecisionSnapshot` and returns `AssignmentRequest` IDs. The controller checks eligibility, creates the routes and executes and validates the batch. The Boolean sums follow the course CP-SAT example. Solving the objectives one at a time avoids arbitrary weights. Only proven optima are fixed. The code also reports time limits and solver statuses, uses integer millisecond objective costs, keeps a previous valid solution if needed, and raises explicit model errors.

Normal allocation now uses CP-SAT. Script and route modes remain available, and nearest-feasible allocation is a comparison under the same road and deadline rules. We pinned OR-Tools 9.15.6755 in the project environment and `requirements.txt`.

This stage passed **102 tests**, keeping 72 and adding 30. Tests covered objectives and constraints, real conflicts and responder choice, exhaustive small comparisons, status and time-limit handling, replay, current-only input and CLI and metric behaviour. Two CLI combinations that previously failed became valid automatic modes, so their tests were updated to match the interface change.

In strict mode with cutoff .20, CP-SAT handled 6/7 versus nearest 5/7 in Scenario 1, tied at 11/12 in Scenario 2, and handled 13/20 versus nearest 15/20 in Scenario 3. An equal-cost early choice put responders with different skills in different places for later medical calls. All recorded local objectives were proved. Repeating the runs reproduced the assignments and metrics for the pinned setup. We kept the unexpected result rather than adding urgency or future knowledge. [Tests and metrics](TESTING.md) · [Saved comparison](results/allocation_comparison.json)

Limits at this point included decisions for the current moment only, no objective for preserving rare skills, waiting age or safety, ties that can affect later calls, rounding in the objective, Python overhead outside a hard time limit, and estimated road times. HMM and final exports still followed later. An optimal current choice can still lead to worse full-run coverage.

## 5. Let historical traffic guide route choice (8 November 2026)

The user rejected multiplying the Bayesian and HMM slowdown factors or taking their maximum. That could make an Open road slower than normal or count congestion twice. The assignment uses normal time for Open and 1.5 times normal for Congested. We approved Forward filtering with a separate route preference, first for exact time ties and then for an optional bounded detour.

`hmm.py` follows slides 17–23. The initial distribution describes \(X_1\), so the first step applies the reading. Later steps add up transition contributions, apply the new reading and normalize. Each road direction is processed once before the run and keeps the Low, Medium and High probabilities. Missing history uses that scenario's prior, which differs in Scenario 2. We never borrow reverse evidence. The age and spacing of readings are unknown, so they do not become simulation events or one transition per second.

`traffic_routing.py` adds normal seconds × probability of High traffic for each route edge. This is our comparison score for historical exposure. The tie policy compares (Bayesian seconds, exposure). The bounded policy keeps useful time/exposure pairs and compares (exposure, seconds) within the time allowance, with a required improvement. This extends ordinary UCS. A 100,000-label guard raises an error on excessive search. Plain Bayesian-only UCS remains available. The HMM integration keeps the Bayesian probability and time formulas, the road cutoff, and the CP-SAT objective.

We fixed the allowance at 5% and the minimum exposure reduction at 10% before testing every scenario. The simulator passes endpoints and the strict remaining arrival budget, checks the chosen road durations, and uses the selected travel seconds for arrival and treatment timing. Strict mode blocks a detour that would arrive late. In late mode a detour can turn an on-time option into a late one. The allocator receives one route per pairing. These effects are documented and tested.

This stage passed **121 tests**, keeping 102 and adding 19. Tests checked worked probabilities, sums over enumerated hidden paths, priors and directions, bad inputs, exact and near ties, bounded decisions, label search against enumerated small graphs, timing and CLI. The 36-run comparison records assignments, scores, time differences, blockage bounds and changes from Bayesian-only.

Neither HMM policy changed a committed route, assignment, handled count, deadline count or response mean across three scenarios, two allocators and two deadline modes. Bounded routing changed seven of 676 reachable endpoint pairs in Scenario 3 and zero in Scenarios 1 and 2. Exact tie routing changed none. N3 → H1 gets 44.96% lower exposure for 2.22% more estimated time, but the run did not use that route. We kept the fixed settings and the earlier Scenario 3 result. This shows the routing preference can have an effect without demonstrating a dispatch improvement. [Saved HMM comparison](results/traffic_comparison.json)

Live data and calibration were unavailable. Real road failures and recovery stayed outside the model. At this checkpoint final files and standalone validation were still to come. The traffic score and estimated times do not establish real-world safety.

## 6. Export and independently check the plan (8 November 2026)

The user requested the assignment's exact output shape and wanted disappointing results preserved. We checked assignment sections 3, 5 and 8 and the scenario README before coding. Section 5.1 requires a list of rows with `responder_id`, `incident_id`, `path` and `time`. Time is the start of dispatch. Section 5.2 gives four required metrics and asks how unhandled work affects them. It does not prescribe a machine-readable statistics format.

The exporter copies the existing simulation assignments and summary into the required files. It adds no arrival fields or settings wrapper to the plan, and it keeps the existing allocation, timing, routing and HMM settings. We chose the working directory for explicit runs because the assignment gives no output folder. `--output-dir` overrides it, comparisons use separate folders, and route inspection is read-only. Scripted and normal runs export. The later menu uses `results/menu/ScenarioN/` and prints both files.

The replay uses original roads, responders and incidents and the shared tested Bayesian inference. It reconstructs road costs, locations, readiness, travel, treatment, deadlines and metrics without calling simulation, search, graph construction, allocation or the summary function. The exporter checks those results against the existing run. The repeated timing calculation is a cross-check. Early tests caught generated code reading `Responder.location` on the original record, which has `start_location`. We fixed the field before deployment.

A partial or empty plan can pass validation and still have poor coverage. Strict deadlines remain the main mode. The late experiment reports missed deadlines and only passes under the relaxed rule. Unhandled calls count as missed in the all-incident percentage and stay out of the response mean. No handled calls means N/A for the mean. Invalid plans get errors instead of performance scores.

This stage passed **145 tests**, keeping 121 and adding 24. Checks cover schema and malformed JSON, references, skills, release, readiness, overlap, treatment, location, directed roads, Bayesian durations and cutoff, strict and late outcomes, empty plans, dispatch time, corrupted data, CLI exports and validator exit codes. Export integration runs 18 combinations across three scenarios and three route policies with both deadline modes. Existing CLI tests got separate output directories because runs now write files. Their behaviour checks were kept.

The six saved strict and late CLI examples pass independent replay and match simulation commitments and metrics. Strict CP-SAT handles 6/7, 11/12 and 13/20. Late mode handles all calls but misses 2, 2 and 9 deadlines. Means and counts stayed the same. We kept the HMM and Scenario 3 findings. [Saved plan checks](results/plan_export_validation.json)

Submission work includes the page-limited PDF, GitHub link and access, and oral defence. Real road safety, live traffic, recovery and global optimality are limitations, while the assignment requires a plan and a clear explanation of the model.

## 7. Proposed Critical fallback

The first idea was to offer a higher road cutoff only if a Critical call had no on-time route under the normal cutoff. The user pointed out that two calls can each have a normal route while both depend on the same responder. Another responder could take one call via a fallback and let both be reached.

We revised the idea to compare a normal-only allocation with an expanded allocation on the same decision snapshot. Consider fallback only for a proven increase in Critical coverage. The user questioned requiring the same High, Medium and Low counts, since that would change how Critical-first priority works. They also noted that a route's worst road cannot describe the risk of the whole route. Both choices remain open. Any predicted extra arrival assumes the route is passable. We deferred the extension to focus on verification and submission. [Proposed design](DESIGN.md#proposed-improvement-for-critical-calls)

## Exact first substantive prompt

```text
I've attached my AI practicum assignment, the scenarios and the course slides.

From what I understand, we need to build a system that assigns emergency responders to incidents and finds suitable routes, while taking into account deadlines, responder availability and uncertain road conditions.

We need to combine search, CSPs, Bayesian reasoning and HMMs to do this. Before starting the implementation, I want to figure out how these components should work together and how to structure the project.

Since the assignment is open-ended, I'd like to discuss the possible approaches and important design decisions first. Use the course slides as the main reference, but feel free to suggest alternatives and point out problems with my approach.

The goal is to build a working system that I can fully understand, test and defend afterwards.
```
