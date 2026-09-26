# Event dictionary v0

Events are instrumentation contracts. They carry IDs, enums, and measurements;
never response bodies or raw learner content.

| Event | Required properties |
| --- | --- |
| `app_opened` | — |
| `topic_created` | `has_source` |
| `explanation_submitted` | `topic_id`, `version` |
| `debate_started` | — |
| `round_challenge_shown` | `round_no`, `challenge_type`, `latency_ms` |
| `round_response_submitted` | — |
| `round_scored` | `verdict`, `confidence`, `grounding_tier`, `latency_ms` |
| `debate_completed` | `round_count`, `duration_s` |
| `debate_abandoned` | `last_round_no` |
| `verdict_disputed` | — |
| `dispute_resolved` | `outcome` |
| `challenge_flagged` | — |
| `review_due_shown` | `days_late` |
| `next_review_scheduled` | `interval_days` |
| `safety_event` | `category` |

User and topic identifiers may be included where needed for joins, but raw
explanations, responses, attached sources, prompts, and model outputs belong in
their explicit data stores under the retention policy.
