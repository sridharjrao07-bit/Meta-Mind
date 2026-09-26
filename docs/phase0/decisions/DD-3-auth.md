# DD-3 — Authorization path

Status: `PENDING`

## Recommendation to ratify

Use the backend with the Supabase service-role key and app-layer user scoping
as the primary control. Keep RLS as a backstop. Prove enforcement with negative
tests: user A's token against user B's data returns 404/403 and direct SQL
returns zero rows.

## Evidence

The Phase 1 schema/auth exit criterion will contain literal negative-test
payloads. RLS policy existence is not accepted as enforcement evidence.

## Decision

Pending Day 5 review.
