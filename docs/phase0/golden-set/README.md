# Golden set v0 — blind labeling packet

This directory is evaluation-only. It must never be used as prompt-development
data. The product owner owns labels; the build agent may prepare cases but may
not assign, revise, or silently normalize labels.

## Labeling procedure

1. Read the topic context, challenge, and learner response.
2. Assign exactly one verdict from the frozen taxonomy.
3. Score correctness, responsiveness, completeness, and calibration from 0–3.
4. Record a short rationale and confidence.
5. Do not consult model output or a proposed label while labeling.
6. Record disagreements with the lead as edge-case decisions.

The packet starts with 30 required rows. Empty labels are intentional until
human review is complete.
