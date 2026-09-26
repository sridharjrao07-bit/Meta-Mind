# MetaMind

MetaMind is an adult-learning product built around retrieval-through-defense:
the learner explains, an AI challenger probes, the learner defends, an
independent scorer grades, and deterministic code schedules the next review.

## Current phase

Phase 0 — spike and decisions. No product code is written in this phase.
The Phase 0 artifacts are throwaway evaluation harnesses, human-labeling
materials, safety protocols, and decision records.

## Plan of record

The approved plan of record is maintained in the project workspace and governs
scope, gates, evidence standards, and change control.

## Working agreements

- Keep challenger, scorer, grounding, and scheduler responsibilities separate.
- Treat all learner-authored text as untrusted input.
- Never edit human golden-set labels through automation.
- Commit one coherent change at a time with evidence in the commit message.
- Do not add product code before the Phase 0 exit gate is signed off.

See [`docs/phase0/README.md`](docs/phase0/README.md) for the active Phase 0
work plan.
