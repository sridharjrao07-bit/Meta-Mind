# Rubric v0

The scorer evaluates four dimensions independently on a 0–3 scale. The scorer
receives only the challenge, response, and rubric; it never receives challenger
intent or hidden evaluation notes.

| Dimension | 0 | 1 | 2 | 3 |
| --- | --- | --- | --- | --- |
| Correctness | materially wrong | mixed or major omission | mostly correct | correct and precise |
| Responsiveness | does not address challenge | tangential | addresses core | directly resolves the challenge |
| Completeness | absent | fragmentary | sufficient core | covers relevant edge cases |
| Calibration | bluffing or unjustified certainty | confidence poorly matched | mostly calibrated | confidence accurately matches knowledge |

## Classification rules

- `failed` is reserved for confident error, not ordinary ignorance.
- `conceded` is positive when the learner is honest and calibrated.
- `rebutted` requires Tier A source support or Tier C cross-model agreement.
- `unassessable` causes no mastery change and enters the review queue.

The product owner labels examples blind. The build agent may propose examples,
but must never assign or silently change their labels.
