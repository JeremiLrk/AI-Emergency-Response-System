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
