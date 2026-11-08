# LLM collaboration record

The original first substantive prompt is preserved verbatim in `README.md`.
The supplied pasted chat was read to recover design context.

Accepted: Python, handwritten UCS, separate probabilistic/route/allocation
components, later OR-Tools CP-SAT, online incident visibility, non-preemptive
dispatch, and incremental tests.

Corrected: the earlier assistant proposed an HMM over road accessibility
Open/Congested/Blocked and imagined newly arriving traffic observations. The
actual model is traffic Low/Medium/High, with historical sequences available
before simulation. `Scenarios/README.md` confirms this directly.

The previous Work checkpoint could not find the archive because it checked the
English Desktop path rather than the redirected OneDrive/Bureaublad location.
After the user identified the repository, the extracted scenarios were found
there. Schema compatibility claims are now based on all three real scenarios,
not just synthetic fixtures. Their README also supplies exact units and local
weather semantics, resolving earlier unknowns.

The assistant wrote typed loaders, a graph adapter and test cases, retained the
handwritten UCS foundation, and documented unresolved modeling limitations.
It did not implement the remaining required AI components or claim the whole
assignment is complete. That foundation was followed by Bayesian inference as recorded below; allocation remains deferred.

Record the exact model/tool names used from the user's app history when writing
the final report; do not invent a model version from the generated code.

Important limitations to defend: inferred road routing can be wrong; traffic history
has no physical time interval; initial busy responders lack completion positions;
traffic multipliers are assumptions; estimated arrival validity does not prove
true-world reachability. See `DESIGN.md` for consequences and alternatives.


## Bayesian implementation after user design review

The user first requested an explanation without implementation. The assistant
checked the course slides and actual scenario CPTs and worked through Scenario1
N1->N2: weights .00012/.00384/.00441, normalizer .00837. The user accepted the
calculations but asked to retain full distributions and avoid interpreting MAP
as certainty. Implementation was explicitly authorized only after that review.

Accepted: exact factor multiplication, local known weather, unknown-weather
marginalization, absent-source likelihoods omitted, directed evidence, rejection
of duplicates/conflicting weather, and separation of Bayesian inference from
routing decisions. The module retains every road's full posterior.

Changed from the earlier design: automatic MAP conversion is not used. The
assistant selected a documented per-edge blockage threshold plus conditional
traversal-time cost as the initial probability-aware routing policy. The API/CLI
require a user-selected threshold; .20 is an illustrative evaluation setting,
not an assignment requirement or established safe default. A route-level union
bound is reported instead of assuming independent road failures. UCS is unchanged.

The user requested parameters, preconditions/postconditions, tests and updated
design/reflection notes. New modules document these contracts. All 39 tests pass,
including 22 new tests and 845 additional Bayesian-graph pair comparisons.

Critical findings: Scenario2 disconnects at threshold .20 (60/132 distinct pairs
reachable). Multiple accepted roads can exceed the per-edge risk threshold in
route-level blockage probability. UCS can prefer a faster riskier accepted path
over a slower safer one. Conditional-time scores are not unconditional arrivals,
and correlated sources can produce overconfidence. Threshold sensitivity was
measured rather than claiming one threshold is best. No actual dispatch metrics,
true-state validation, HMM, solver or simulation claims are made.


## Event simulation after user review

The user requested a design explanation before code. The discussion used actual
Scenario1 responder readiness, releases and Bayesian travel times, distinguishing
required timestamp/capability/arrival/service rules from event-queue choices.
The user approved batching simultaneous events and separating the controller from
the future CSP, then corrected a proposed assumption: the assignment does not
necessarily require abandoning an incident once its arrival deadline is missed.

Accepted correction: strict deadlines are a configurable baseline, and deadline
outcome is separate from incident work status. The simulator supports strict mode
and an allow-late policy with completed+missed results. Strict closure and end-of-run
unhandled closure have explicit reasons; neither is called completed treatment.

Implemented: private event controller, frozen current-state/candidate snapshots,
atomic dispatch validation, non-preemptive travel/service, updated positions,
initial busy readiness, same-time causal closure for zero events, event logging,
script fixtures and CLI integration. Scripts return IDs, not caller-invented
routes/times; the engine generates/validates current candidates using UCS. No CSP
or greedy allocation was introduced. The current interface prevents accidental
future-incident exposure, not malicious file access by arbitrary Python callbacks.

All 72 tests pass, preserving the existing 39 and adding 33 checks. Verification
includes timing edge cases, immutable/no-lookahead snapshots, invalid-batch
atomicity, separate late outcomes, script/CLI behavior, all three real streams with
no-op dispatch, and independent replay of four real Scenario1 commitments.

Findings/limits: the sample script deliberately handles only four of seven
incidents; it tests execution rather than optimal coverage. Same-time script
batches are consumed once; custom callbacks can chain zero-duration jobs. Float
times retain precision without fuzzy early releases, but boundary rounding remains
a limitation and unrepresentable positive clock advances are rejected. Initially
busy completion location is assumed to be the supplied start node. Rerouting,
preemption, hidden-road failure execution, HMM, CP-SAT and final output files remain
deferred. Modeled deadline success must not be described as an actual guarantee.


## CP-SAT allocation after objective correction

The assistant proposed Boolean assignment variables, optional unassignment,
lexicographic priority coverage, deadline ranking and response minimization.
The user accepted the variable/constraint/CP-SAT design but rejected deadline
ranking before response time: an earlier deadline does not justify a longer
response when both are feasible. The approved implemented objective is priority
coverage, then on-time coverage when late responses are permitted, then predicted
response time. No EDF/slack/urgency rank was implemented.

The allocator consumes DecisionSnapshot only and returns AssignmentRequest IDs.
The controller still owns eligibility, routing candidates and execution; it
independently validates solver output. Boolean sums mirror the course CSP slides'
OR-Tools example. Exact sequential objective stages avoid arbitrary priority/time
weights; only OPTIMAL stages are fixed. Status/time-limit diagnostics, integer
millisecond objective coefficients, retained incumbents and explicit model errors
were added. Normal CLI runs use CP-SAT; scripted fixtures and route mode remain.
Nearest-feasible greedy allocation provides a comparison on identical road/deadline
policies. OR-Tools 9.15.6755 was installed in a project .venv and requirements pinned.

All 102 tests pass: the previous 72 plus 30 new tests for objective choices,
constraints, actual conflicts/responder choice, exhaustive small-model optimum,
status/fallback branches, replay validity, snapshot boundaries and metric/CLI
semantics. Two historical invalid CLI cases became legitimate automatic modes;
tests were updated for that intentional interface change, not removed to hide
assignment failures.

Evaluation challenged the idea that local optimization guarantees better full-run
performance. At Bayesian threshold .20 in strict mode, CSP handles 6/7 versus
nearest 5/7 in Scenario1, ties 11/12 in Scenario2, but handles 13/20 versus nearest
15/20 in Scenario3. Equal-cost initial placement of different-capability units
affects future medical calls. All recorded local solves were proven optimal.
Results were retained and explained rather than adding an unapproved urgency or
future-aware heuristic. A repeated evaluation matched JSON-normalized commitments
and metrics for the pinned version/configuration. See TESTING.md and the checked-in
comparison JSON for strict/late counts, means and per-priority coverage.

Remaining limitations: immediate-only horizon, no explicit scarcity/aging/safety
objective, tie sensitivity, objective quantization, wall-time overhead not hard
preempted, and execution using estimates rather than true road failures. At this
checkpoint HMM and final submission-output generation were deferred. Solving optimally at an event
does not establish optimal global coverage or calibrated arrival guarantees.

## HMM implementation after integration review (2026-11-08)

The user rejected multiplying/maximizing Bayesian and traffic slowdown factors:
the assignment fixes Open normal and Congested1.5 times normal, and an extra HMM
factor could violate that interpretation or count congestion twice. They approved
Forward filtering plus an independent historical exposure routing preference,
with exact shortest-path tie-breaking first and an optional bounded trade-off.

Implemented hmm.py using course HMM slides17-23: initial as P(X1), emission first,
then prediction (sum, not max) and emission/normalization for each later ordinal.
No observations become simulation events. Each directed road is filtered once
at startup; full Low/Medium/High posteriors retained, missing histories use that
scenario's prior (Scenario2 differs), and reverse evidence is never borrowed.
Unknown age/sampling interval prevents inventing transitions per simulation second.

Implemented traffic_routing.py with Q=sum normal_seconds*P(High). This is our own
reference-exposure preference, not a supplied physical time/safety model. Exact
ties minimize (Bayesian seconds,Q); bounded routing uses a Pareto-label search
to minimize (Q,seconds) inside a travel bound, with a required exposure reduction.
General constrained search is an extension beyond course scalar UCS and has an
explicit 100000-label failure guard, not an undocumented approximation/fallback.
Original Bayesian-only UCS remains available. No Bayesian posterior, edge-time
formula, CSP objective or blockage threshold rule was changed.

Before benchmarking, maximum extra travel5% and minimum exposure reduction10%
were declared. These settings apply to all scenarios, without result tuning.
Simulator injection passes current endpoints/strict budget only, verifies route
edge durations, and uses actual selected Bayesian seconds for arrival/completion
and availability. Strict deadlines cap detours; late mode may deliberately choose
a route that turns an on-time possibility into a late arrival. This limitation is
tested/documented, not concealed. Only one route per pair reaches the allocator.

All121 tests pass: prior102 unchanged plus19 covering actual worked probabilities,
brute-force hidden-path sums, priors/direction, validation, exact/near ties,
bounded acceptance, Pareto correctness against enumerated small DAGs, time-budget
integration and CLI. Benchmark reports36 independent runs with full assignments,
scores, time differences, blockage bounds and changes from Bayesian-only.

Result: no changed committed routes/assignments, handled counts, deadlines or
response means under either HMM policy in any of the three supplied scenarios,
both allocators and deadline modes. Broader all-pairs routing changes7/676 reachable
pairs in Scenario3 with bounded policy, zero in Scenarios1/2; exact tie changes
none. E.g. N3->H1 gains44.96% lower exposure for2.22% more estimated travel, but
that route is not committed in these runs. This establishes actual route-selection
influence without claiming dispatch benefit. Parameters were NOT enlarged to
improve the benchmark; earlier Scenario3 CSP underperformance remains documented.

At this HMM checkpoint: historical proxy calibration/live evidence unavailable,
true-road failure/recovery and final submission outputs/standalone validation deferred.
Full distributions and explicit score/time separation aid review but do not
establish real-world arrival guarantees or route safety.

## Required artifacts and independent validator (2026-11-08)

The user requested completion of assignment output/validation requirements, while
preserving disappointing benchmarks and avoiding invented schemas or duplicate
decision logic. Before implementation, Assignment1 (1).pdf sections3/5/8 and
Scenarios/README.md were inspected. Section5.1 explicitly specifies a top-level
list of responder_id,incident_id,path,time; time is assignment start/departure.
Section5.2 requires four performance metrics and explanations of denominators and
unhandled work, but does not prescribe a machine-readable statistics schema.

Accepted: direct projection of existing SimulationResult assignments, existing
summarize metrics, readable statistics text with explicit estimates/units/settings,
and independent original-data replay before publishing. No arrival fields or
metadata wrapper were invented for plan.json. No allocator/event/search policy or
HMM parameters were changed. Output location was unspecified, so current working
directory is default, --output-dir explicit, and --compare separates allocator
subdirectories. Diagnostic --route remains read-only; script/normal runs export.

plan_validation.py uses original roads/responders/incidents and shared tested
Bayesian inference, independently reconstructing directed costs, readiness,
locations, travel, treatment, deadlines and metrics. It does not call simulation,
search, graph building, allocator or summarize, or trust recorded simulation times.
The exporter checks replayed travel/arrival/completion and statistics against the
same existing final result before writing. The duplication here is intentional
independent validation, not a second assignment/timing engine for output generation.
The first test run exposed a generated reference to Responder.location; original
input records use start_location. That implementation mistake was corrected before
deployment, illustrating why original-data tests were needed.

Validity and quality are separate: unhandled incidents do not invalidate a partial
plan, and a valid empty plan can have zero coverage. Strict arrival deadlines remain
default. Explicit allow-late validity is relative to that relaxed experimental
policy and does NOT certify all assignment deadlines; reports expose this and
count late work separately. All-incident deadline percentage includes unhandled
misses; response mean excludes unhandled work, with N/A for no handled incidents.
Invalid plans are not assigned performance statistics to avoid misleading scores.

All145 tests pass: prior121 plus24 for schema/JSON errors, references, capabilities,
releases, readiness, overlap, treatment, location changes, directed roads, Bayesian
cost reconstruction/threshold, strict/late outcomes, empty plans, start-time
semantics, corruption rejection, CLI files and validator exits. Actual export
integration runs18 combinations across all three scenarios and route policies.
Existing CLI test destinations were isolated because normal execution now writes
required files; previous behavioral assertions were kept.

Six saved CLI examples (three scenarios, strict/late) independently validate and
match simulation commitments/metrics. Counts/means remain unchanged: strict CSP
handles6/7,11/12,13/20; late mode handles all but misses2,2,9 deadlines. Historical
HMM exposure and Scenario3 CSP underperformance remain documented without tuning.
results/plan_export_validation.json records the evidence and original-data replay.

Remaining submission work is report.pdf within the assignment's page limit,
GitHub link/access/submission and defence preparation. Do not represent unknown
real-road safety, live traffic, recovery or global optimality as established;
these are limitations rather than extra mandatory implementation requirements.
