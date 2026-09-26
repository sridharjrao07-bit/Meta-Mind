# Phase 0 — Spike and decisions

Phase 0 is a five-day evidence sprint. It produces decisions and evaluation
artifacts, not application code.

## Exit gate

Phase 0 closes only when all of the following are present:

1. DD-1 through DD-5, each with raw artifacts and a recorded decision.
2. Rubric v0 and the frozen six-class verdict taxonomy.
3. Thirty human-labeled golden examples, labeled by the product owner blind.
4. Injection cases I-01 through I-05 completed for the first pass.
5. The topic safety policy.
6. Ratified metric thresholds and the Phase 1 handoff checklist.

## Daily sequence

| Day | Focus | Evidence |
| --- | --- | --- |
| D1 | Harness and golden labeling | labeling packet, decision rules |
| D2 | Challenger/scorer spike | model outputs, latency, conformity |
| D3 | Grounding and injection | planted-error scorecard, case results |
| D4 | Structured output and economics | schema results, cost/latency tables |
| D5 | Evidence review and handoff | signed decision docs, exit checklist |

## Decision records

- [DD-1 Model](decisions/DD-1-model.md)
- [DD-2 Grounding](decisions/DD-2-grounding.md)
- [DD-3 Auth path](decisions/DD-3-auth.md)
- [DD-4 Economics](decisions/DD-4-economics.md)
- [DD-5 Notifications](decisions/DD-5-notifications.md)

## Evidence rules

Narrative claims do not close a phase. Every claim must link to raw terminal
output, literal payloads, direct SQL results, or a human-owned labeling record.
Generated artifacts belong under `artifacts/generated/` and are not committed
unless they are the immutable raw evidence for a decision.
