-- backend/migrations/006_phase6_security.sql
-- Phase 6: Formal Security Audit & Hardening

-- 1. Ensure RLS is enabled on every table in the schema
ALTER TABLE topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE reference_material ENABLE ROW LEVEL SECURITY;
ALTER TABLE debate_rounds ENABLE ROW LEVEL SECURITY;
ALTER TABLE mastery_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE streaks ENABLE ROW LEVEL SECURITY;
ALTER TABLE achievements ENABLE ROW LEVEL SECURITY;
ALTER TABLE exam_dates ENABLE ROW LEVEL SECURITY;
ALTER TABLE scheduled_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE topic_relations ENABLE ROW LEVEL SECURITY;
ALTER TABLE classrooms ENABLE ROW LEVEL SECURITY;
ALTER TABLE classroom_members ENABLE ROW LEVEL SECURITY;

-- 2. Verify and enforce reference_material ON DELETE CASCADE
-- We will drop the existing foreign key and recreate it explicitly to guarantee cascading is applied.
ALTER TABLE reference_material
    DROP CONSTRAINT IF EXISTS reference_material_topic_id_fkey,
    DROP CONSTRAINT IF EXISTS reference_material_user_id_fkey;

ALTER TABLE reference_material
    ADD CONSTRAINT reference_material_topic_id_fkey 
    FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE;

ALTER TABLE reference_material
    ADD CONSTRAINT reference_material_user_id_fkey 
    FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

-- 3. The student classroom UPDATE restriction is currently handled by the fact that
-- only a SELECT policy exists for students (default deny on UPDATE).
-- We explicitly create an instructor-only UPDATE policy to ensure it remains restricted.
DROP POLICY IF EXISTS "classroom_members: instructors manage their classroom" ON classroom_members;

CREATE POLICY "classroom_members: instructors manage their classroom"
    ON classroom_members FOR ALL
    USING (
      EXISTS (
        SELECT 1 FROM classrooms c
        WHERE c.id = classroom_members.classroom_id
          AND c.instructor_id = auth.uid()
      )
    )
    WITH CHECK (
      EXISTS (
        SELECT 1 FROM classrooms c
        WHERE c.id = classroom_members.classroom_id
          AND c.instructor_id = auth.uid()
      )
    );
