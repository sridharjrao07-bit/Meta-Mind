-- MetaMind Phase 7 Migration: Gamification & Transactions
-- Run this to CREATE OR REPLACE the RPC (idempotent, safe to re-run).

-- ── 1. Unique indexes for achievements ──────────────────────────────────────
-- Two partial indexes replace NULLS NOT DISTINCT (requires Postgres 15+).
-- Global badges (topic_id IS NULL):  one row per (user_id, type).
-- Per-topic badges (topic_id IS NOT NULL): one row per (user_id, type, topic_id).
-- ON CONFLICT DO NOTHING inside the RPC body relies on these indexes.

CREATE UNIQUE INDEX IF NOT EXISTS achievements_user_type_topic_null_idx 
    ON achievements (user_id, type) 
    WHERE topic_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS achievements_user_type_topic_idx 
    ON achievements (user_id, type, topic_id) 
    WHERE topic_id IS NOT NULL;


-- ── 2. Atomic RPC ─────────────────────────────────────────────────────────
-- Everything that happens after a student submits a rebuttal lives in a single
-- PL/pgSQL function so it shares one Postgres transaction:
--
--   a) Update debate_rounds with rebuttal + scoring output
--   b) Upsert mastery_state
--   c) Streak logic (SELECT … FOR UPDATE → branch on lapse/increment/no-op)
--   d) Achievement checks + INSERT … ON CONFLICT DO NOTHING
--   e) Return state to Python (no further DB writes needed in the caller)
--
-- SECURITY DEFINER is used so the function runs with the role that created it
-- (postgres/service role) and can bypass RLS for the internal writes that are
-- already scoped to p_user_id. The function still enforces user ownership on
-- the debate_round UPDATE (WHERE … AND user_id = p_user_id).

CREATE OR REPLACE FUNCTION process_debate_respond_transaction(
    p_round_id        uuid,
    p_user_id         uuid,
    p_topic_id        uuid,
    p_student_rebuttal text,
    p_scoring_criteria text,
    p_verdict          text,
    p_mastery_score    double precision,
    p_failure_mode     text,
    p_weak_point       text,
    p_next_review_due  timestamp with time zone
) RETURNS jsonb AS $$
DECLARE
    -- Streak working variables
    v_streak_row     record;
    v_last_active    date;
    v_today          date    := current_date;
    v_current_streak int;
    v_longest_streak int;
    v_freeze_tokens  int;
    v_streak_was_broken boolean := false;

    -- Post-streak state used for achievement checks
    v_total_rounds   int;
    v_topic_attempts int;
BEGIN
    -- ── a) Persist rebuttal + scoring onto the debate round ──────────────────
    -- The AND user_id = p_user_id clause is the ownership check —
    -- the function does nothing (0 rows updated) if the round doesn't belong
    -- to the calling user, which the Python layer detects via rpc_response.data.success.
    UPDATE debate_rounds
    SET
        student_rebuttal = p_student_rebuttal,
        scoring_criteria = p_scoring_criteria,
        verdict          = p_verdict,
        mastery_score    = p_mastery_score,
        failure_mode     = p_failure_mode,
        weak_point       = p_weak_point
    WHERE id = p_round_id AND user_id = p_user_id;

    -- ── b) Upsert mastery state ───────────────────────────────────────────────
    -- Conflict target is (topic_id) — the PK / unique column on mastery_state.
    INSERT INTO mastery_state (
        topic_id, user_id, current_score, last_reviewed,
        next_review_due, total_attempts, low_score_streak
    )
    VALUES (
        p_topic_id, p_user_id, p_mastery_score, now(),
        p_next_review_due, 1,
        CASE WHEN p_mastery_score < 0.5 THEN 1 ELSE 0 END
    )
    ON CONFLICT (topic_id) DO UPDATE SET
        current_score    = EXCLUDED.current_score,
        last_reviewed    = EXCLUDED.last_reviewed,
        next_review_due  = EXCLUDED.next_review_due,
        total_attempts   = mastery_state.total_attempts + 1,
        low_score_streak = CASE
            WHEN EXCLUDED.current_score < 0.5 THEN mastery_state.low_score_streak + 1
            ELSE 0
        END;

    -- ── c) Streak logic ───────────────────────────────────────────────────────
    -- FOR UPDATE prevents a concurrent call for the same user from reading
    -- the streak row before this transaction's write is committed (freeze-token
    -- race guard). The second concurrent call will block until this commits,
    -- then it will see last_active_date = today and hit the no-op branch.
    SELECT * INTO v_streak_row
    FROM streaks
    WHERE user_id = p_user_id
    FOR UPDATE;

    IF NOT FOUND THEN
        -- First ever debate for this user
        INSERT INTO streaks (user_id, current_streak, longest_streak, freeze_tokens, last_active_date)
        VALUES (p_user_id, 1, 1, 0, v_today);
        v_current_streak := 1;

    ELSE
        v_last_active    := v_streak_row.last_active_date;
        v_current_streak := v_streak_row.current_streak;
        v_longest_streak := v_streak_row.longest_streak;
        v_freeze_tokens  := v_streak_row.freeze_tokens;

        IF v_last_active = v_today THEN
            -- Already active today — no-op (idempotent second call)
            NULL;

        ELSIF v_last_active = v_today - interval '1 day' THEN
            -- Consecutive day — increment
            v_current_streak := v_current_streak + 1;
            IF v_current_streak > v_longest_streak THEN
                v_longest_streak := v_current_streak;
            END IF;
            UPDATE streaks SET
                current_streak   = v_current_streak,
                longest_streak   = v_longest_streak,
                last_active_date = v_today
            WHERE user_id = p_user_id;

        ELSE
            -- Lapsed (gap > 1 day)
            IF v_freeze_tokens > 0 THEN
                -- Consume one freeze token; streak survives
                v_current_streak := v_current_streak + 1;
                IF v_current_streak > v_longest_streak THEN
                    v_longest_streak := v_current_streak;
                END IF;
                -- AND freeze_tokens > 0 is the atomic race guard at the SQL level:
                -- if two concurrent calls both read freeze_tokens = 1 before either
                -- commits, only the first UPDATE will satisfy freeze_tokens > 0;
                -- the second sees freeze_tokens = 0 after the first commits and
                -- would fall to the ELSE branch — but FOR UPDATE prevents that race
                -- entirely by serializing concurrent calls at the row lock.
                UPDATE streaks SET
                    freeze_tokens    = freeze_tokens - 1,
                    current_streak   = v_current_streak,
                    longest_streak   = v_longest_streak,
                    last_active_date = v_today
                WHERE user_id = p_user_id AND freeze_tokens > 0;

            ELSE
                -- No freeze tokens — reset streak
                v_streak_was_broken := true;
                v_current_streak    := 1;
                UPDATE streaks SET
                    current_streak   = 1,
                    last_active_date = v_today
                WHERE user_id = p_user_id;
            END IF;
        END IF;
    END IF;

    -- ── d) Achievement checks + atomic inserts ────────────────────────────────
    -- Read post-update state (these are the counts after the writes above).
    SELECT count(*) INTO v_total_rounds
    FROM debate_rounds
    WHERE user_id = p_user_id AND student_rebuttal IS NOT NULL;

    SELECT total_attempts INTO v_topic_attempts
    FROM mastery_state
    WHERE topic_id = p_topic_id AND user_id = p_user_id;

    -- Rule 1: First Debate Completed (global — topic_id IS NULL)
    IF v_total_rounds = 1 THEN
        INSERT INTO achievements (user_id, type, topic_id)
        VALUES (p_user_id, 'First Debate Completed', NULL)
        ON CONFLICT DO NOTHING;
    END IF;

    -- Rule 2: 3-Day Streak (global)
    IF v_current_streak >= 3 THEN
        INSERT INTO achievements (user_id, type, topic_id)
        VALUES (p_user_id, '3-Day Streak', NULL)
        ON CONFLICT DO NOTHING;
    END IF;

    -- Rule 3: Comeback — rebuilt streak to ≥3 after a lapse this very update (global)
    IF v_streak_was_broken AND v_current_streak >= 3 THEN
        INSERT INTO achievements (user_id, type, topic_id)
        VALUES (p_user_id, 'Comeback', NULL)
        ON CONFLICT DO NOTHING;
    END IF;

    -- Rule 4: Perfect Score — held_up on the first attempt for this topic (per-topic)
    IF p_verdict = 'held_up' AND v_topic_attempts = 1 THEN
        INSERT INTO achievements (user_id, type, topic_id)
        VALUES (p_user_id, 'Perfect Score', p_topic_id)
        ON CONFLICT DO NOTHING;
    END IF;

    -- ── e) Return post-transaction state ─────────────────────────────────────
    -- Python only reads this for display / response construction.
    -- No further DB writes happen in the caller after this point.
    RETURN jsonb_build_object(
        'success',            true,
        'streak_was_broken',  v_streak_was_broken,
        'current_streak',     v_current_streak,
        'total_rounds',       v_total_rounds,
        'topic_attempts',     v_topic_attempts
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
