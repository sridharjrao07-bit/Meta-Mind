# Verdict taxonomy v0

This taxonomy is frozen for v1. Any change requires a decision record and lead
sign-off.

| Verdict | Meaning | Mastery signal |
| --- | --- | --- |
| `defended` | The response fully withstands the challenge. | Strong positive |
| `partially_defended` | The core holds, but the specific challenge is incomplete. | Small positive |
| `rebutted` | The learner shows that the challenge itself is wrong, with grounding support. | Strong positive |
| `conceded` | The learner honestly admits not knowing or correctly changes their mind. | Positive |
| `failed` | The learner confidently asserts a materially wrong claim. | Negative |
| `unassessable` | Off-topic, incoherent, or gaming; no reliable judgment is possible. | No change |

## Anti-bluffing invariant

Under every allowed tuning, `conceded` must produce a better downstream outcome
than `failed`: mastery delta, review interval, and all derived effects. A bare
“I don't know” is a weak concession; an honest, calibrated uncertainty with a
reasoned guess is strong. Wrong-but-aware is `conceded`, not `failed`.
