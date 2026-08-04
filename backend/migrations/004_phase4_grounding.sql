-- backend/migrations/004_phase4_grounding.sql
-- Phase 4: Direct user_id scoping on reference_material + flag_reason column on debate_rounds

-- 1. Add user_id to reference_material for direct defense-in-depth scoping
ALTER TABLE reference_material
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;

-- Backfill user_id from topics for any existing rows
UPDATE reference_material rm
SET user_id = t.user_id
FROM topics t
WHERE rm.topic_id = t.id AND rm.user_id IS NULL;

-- 2. Update RLS policies to enforce direct user_id check
DROP POLICY IF EXISTS "reference_material: users own via topic" ON reference_material;
DROP POLICY IF EXISTS "reference_material: users own their rows" ON reference_material;

CREATE POLICY "reference_material: users own their rows"
    ON reference_material FOR ALL
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- 3. Add flag_reason to debate_rounds for student dispute feedback
ALTER TABLE debate_rounds
    ADD COLUMN IF NOT EXISTS flag_reason TEXT;

-- 4. Add index for fast retrieval by topic_id and user_id
CREATE INDEX IF NOT EXISTS idx_reference_material_topic_user
    ON reference_material(topic_id, user_id, created_at DESC);
