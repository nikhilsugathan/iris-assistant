# Research Decisions

## Current Working Assumptions

- IRIS should remain local-first.
- Cloud services can remain optional fallbacks.
- The target is Cody-like behavior, not Cody's private internals.
- The highest-value gains likely come from orchestration and memory, not just model size.
- Proactivity should be bounded and user-controllable.

## Open Questions For Review

- Is the phased roadmap too broad for the current architecture?
- Should memory be split into multiple stores now, or staged later?
- Should proactivity be introduced only after verification and goal memory exist?
- How much of the reasoning-summary layer should be rule-based versus model-generated?
