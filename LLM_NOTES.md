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
assignment is complete. Model-specific inference and allocation are next steps.

Record the exact model/tool names used from the user's app history when writing
the final report; do not invent a model version from the generated code.

Important limitations to defend: MAP road routing can be wrong; traffic history
has no physical time interval; initial busy responders lack completion positions;
traffic multipliers are assumptions; estimated arrival validity does not prove
true-world reachability. See `DESIGN.md` for consequences and alternatives.
