-- backend/migrations/002_add_reference_notes.sql

-- Add reference_notes to topics table to support Phase 1 grounding
ALTER TABLE topics ADD COLUMN reference_notes TEXT;
