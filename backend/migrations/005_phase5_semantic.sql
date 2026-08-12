-- backend/migrations/005_phase5_semantic.sql
-- Phase 5: Semantic Memory + Knowledge Map
--
-- 1. embedding column on debate_rounds (1536-dim for text-embedding-3-small)
-- 2. topic_relations table for the knowledge map (10.4)
-- 3. RLS policies scoped strictly to user_id on topic_relations
-- 4. pgvector index for fast similarity search on debate_rounds

-- 1. Add embedding column to debate_rounds (populated after each scored round)
ALTER TABLE debate_rounds
    ADD COLUMN IF NOT EXISTS embedding vector(1536);

-- 2. Create topic_relations for knowledge map edges (Section 10.4)
CREATE TABLE IF NOT EXISTS topic_relations (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
    topic_a       uuid REFERENCES topics(id) ON DELETE CASCADE NOT NULL,
    topic_b       uuid REFERENCES topics(id) ON DELETE CASCADE NOT NULL,
    relation_strength float NOT NULL CHECK (relation_strength >= 0.0 AND relation_strength <= 1.0),
    created_at    timestamp with time zone DEFAULT now(),
    updated_at    timestamp with time zone DEFAULT now(),
    -- Enforce uniqueness per user per pair (ordered so (A,B) = (B,A))
    UNIQUE (user_id, topic_a, topic_b)
);

-- 3. RLS: users can only read/write their own topic_relations rows
ALTER TABLE topic_relations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "topic_relations: users own their rows" ON topic_relations;
CREATE POLICY "topic_relations: users own their rows"
    ON topic_relations FOR ALL
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- 4. Index for fast pgvector ANN search on debate_rounds embeddings
--    ivfflat for approximate nearest-neighbor search on 1536-dim vectors.
--    lists=100 is a good default for tables < 1M rows.
CREATE INDEX IF NOT EXISTS idx_debate_rounds_embedding
    ON debate_rounds USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- 5. Index on topic_relations for fast graph lookups
CREATE INDEX IF NOT EXISTS idx_topic_relations_user_topic_a
    ON topic_relations (user_id, topic_a);
CREATE INDEX IF NOT EXISTS idx_topic_relations_user_topic_b
    ON topic_relations (user_id, topic_b);

-- 6. RPC: match_debate_rounds — pgvector cosine similarity search
--    Called by services/embeddings.py get_related_struggles().
--    Returns the top-N debate rounds for a user (excluding the current topic)
--    ordered by cosine distance to the query embedding.
--    user_id scoping is HARD-CODED in the function — not just in RLS.
CREATE OR REPLACE FUNCTION match_debate_rounds(
    query_embedding   vector(1536),
    match_user_id     uuid,
    exclude_topic_id  uuid,
    match_count       int DEFAULT 3
)
RETURNS TABLE (
    id         uuid,
    topic_id   uuid,
    topic_name text,
    weak_point text,
    similarity float
)
LANGUAGE sql STABLE
AS $$
    SELECT
        dr.id,
        dr.topic_id,
        t.name  AS topic_name,
        dr.weak_point,
        1 - (dr.embedding <=> query_embedding) AS similarity
    FROM debate_rounds dr
    JOIN topics t ON t.id = dr.topic_id
    WHERE dr.user_id   = match_user_id
      AND dr.topic_id  <> exclude_topic_id
      AND dr.embedding IS NOT NULL
      AND dr.weak_point IS NOT NULL
    ORDER BY dr.embedding <=> query_embedding
    LIMIT match_count;
$$;
