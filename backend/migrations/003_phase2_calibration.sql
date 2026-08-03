-- backend/migrations/003_phase2_calibration.sql
-- Phase 2: add slider_touched to debate_rounds for calibration tracking.
--
-- INTENT: The confidence slider defaults to 50% in the UI for UX friendliness.
-- Without this column, an untouched default would be stored as a real prediction,
-- silently corrupting calibration analytics. slider_touched=false rows are excluded
-- from calibration curve calculations. Cheap to add now; impossible to reconstruct
-- retroactively once real usage data is flowing.
--
-- compression_summary already exists from the Phase 1 schema (001_phase1.sql).
-- predicted_score already exists from the Phase 1 schema (001_phase1.sql).
-- This migration adds only the new column.

ALTER TABLE debate_rounds
    ADD COLUMN IF NOT EXISTS slider_touched BOOLEAN NOT NULL DEFAULT FALSE;
