-- Phase 8: Advanced Pedagogical Modes
-- Adds planted_error column to debate_rounds for the reverse-role mode (Catch the Error).
-- The agent intentionally introduces a factual error in its explanation, which the student must find.
-- This column stores the expected error so the Scoring Agent can grade the student's rebuttal.

ALTER TABLE debate_rounds ADD COLUMN IF NOT EXISTS planted_error text;
