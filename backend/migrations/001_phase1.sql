-- MetaMind Phase 1 Migration
-- Section 7 of the Development Plan — full schema + RLS
-- Run this in the Supabase SQL editor (or via Supabase CLI).
--
-- The pgvector extension and all 10 tables are created here.
-- Only the tables Phase 1 writes to have their RLS fully wired:
--   topics, debate_rounds, mastery_state
-- Remaining tables are created with RLS enabled but no policies yet —
-- they will be populated in the phases that use them.
-- This is intentional: an empty RLS policy set means those tables are
-- completely locked (no reads, no writes) until the relevant phase adds policies.

-- ── Extensions ────────────────────────────────────────────────
create extension if not exists vector;

-- ── Topics ────────────────────────────────────────────────────
create table if not exists topics (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid references auth.users(id) on delete cascade not null,
  name        text not null check (char_length(name) between 1 and 200),
  course      text,
  created_at  timestamp with time zone default now()
);

alter table topics enable row level security;

create policy "topics: users own their rows"
  on topics for all
  using  (user_id = auth.uid())
  with check (user_id = auth.uid());

-- ── Reference Material ────────────────────────────────────────
-- Phase 4 populates this; created now so schema is complete.
create table if not exists reference_material (
  id          uuid primary key default gen_random_uuid(),
  topic_id    uuid references topics(id) on delete cascade not null,
  content     text,
  source_type text default 'text' check (source_type in ('text', 'ocr_scan')),
  embedding   vector(1536),
  created_at  timestamp with time zone default now()
);

alter table reference_material enable row level security;

-- RLS via join: a user can only see reference_material for their own topics.
create policy "reference_material: users own via topic"
  on reference_material for all
  using (
    exists (
      select 1 from topics t
      where t.id = reference_material.topic_id
        and t.user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from topics t
      where t.id = reference_material.topic_id
        and t.user_id = auth.uid()
    )
  );

-- ── Debate Rounds ─────────────────────────────────────────────
create table if not exists debate_rounds (
  id                   uuid primary key default gen_random_uuid(),
  topic_id             uuid references topics(id) on delete cascade not null,
  user_id              uuid references auth.users(id) on delete cascade not null,
  round_type           text default 'standard' check (round_type in ('standard', 'reverse_role')),
  input_mode           text default 'text' check (input_mode in ('text', 'voice', 'sketch')),
  student_explanation  text,
  predicted_score      float check (predicted_score between 0.0 and 1.0),

  -- Debate Agent generation output (Section 11.1)
  acknowledgment       text,
  focus_area           text,
  challenge_type       text check (challenge_type in ('edge_case', 'counterexample', 'boundary_condition', 'new_context')),
  challenge            text,

  student_rebuttal     text,
  compression_summary  text,

  -- Debate Agent scoring output (Section 11.2)
  scoring_criteria     text,
  verdict              text check (verdict in ('held_up', 'partial', 'failed')),
  mastery_score        float check (mastery_score between 0.0 and 1.0),
  failure_mode         text check (failure_mode in ('shallow_memorization', 'wrong_mental_model', 'correct_but_unclear', 'partial_gap')),
  weak_point           text,

  flagged_incorrect    boolean default false,
  embedding            vector(1536),
  created_at           timestamp with time zone default now()
);

alter table debate_rounds enable row level security;

create policy "debate_rounds: users own their rows"
  on debate_rounds for all
  using  (user_id = auth.uid())
  with check (user_id = auth.uid());

-- ── Mastery State ─────────────────────────────────────────────
create table if not exists mastery_state (
  topic_id          uuid primary key references topics(id) on delete cascade,
  user_id           uuid references auth.users(id) on delete cascade not null,
  current_score     float check (current_score between 0.0 and 1.0),
  last_reviewed     timestamp with time zone,
  next_review_due   timestamp with time zone,
  total_attempts    int default 0 check (total_attempts >= 0),
  low_score_streak  int default 0 check (low_score_streak >= 0)
);

alter table mastery_state enable row level security;

create policy "mastery_state: users own their rows"
  on mastery_state for all
  using  (user_id = auth.uid())
  with check (user_id = auth.uid());

-- ── Streaks ───────────────────────────────────────────────────
-- Phase 7. Created now; policies added in Phase 7.
create table if not exists streaks (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid references auth.users(id) on delete cascade not null,
  current_streak    int default 0,
  longest_streak    int default 0,
  freeze_tokens     int default 0,
  last_active_date  date
);

alter table streaks enable row level security;

create policy "streaks: users own their rows"
  on streaks for all
  using  (user_id = auth.uid())
  with check (user_id = auth.uid());

-- ── Achievements ──────────────────────────────────────────────
-- Phase 7.
create table if not exists achievements (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid references auth.users(id) on delete cascade not null,
  topic_id    uuid references topics(id) on delete set null,
  type        text not null,
  earned_at   timestamp with time zone default now()
);

alter table achievements enable row level security;

create policy "achievements: users own their rows"
  on achievements for all
  using  (user_id = auth.uid())
  with check (user_id = auth.uid());

-- ── Exam Dates ────────────────────────────────────────────────
-- Phase 9.
create table if not exists exam_dates (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid references auth.users(id) on delete cascade not null,
  course      text not null,
  exam_date   date not null,
  created_at  timestamp with time zone default now()
);

alter table exam_dates enable row level security;

create policy "exam_dates: users own their rows"
  on exam_dates for all
  using  (user_id = auth.uid())
  with check (user_id = auth.uid());

-- ── Scheduled Sessions ────────────────────────────────────────
-- Phase 9.
create table if not exists scheduled_sessions (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid references auth.users(id) on delete cascade not null,
  topic_id       uuid references topics(id) on delete cascade not null,
  proposed_time  timestamp with time zone not null,
  status         text default 'proposed' check (status in ('proposed', 'accepted', 'skipped', 'rescheduled')),
  rationale      text,
  created_at     timestamp with time zone default now()
);

alter table scheduled_sessions enable row level security;

create policy "scheduled_sessions: users own their rows"
  on scheduled_sessions for all
  using  (user_id = auth.uid())
  with check (user_id = auth.uid());

-- ── Topic Relations (Knowledge Map) ──────────────────────────
-- Phase 5.
create table if not exists topic_relations (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid references auth.users(id) on delete cascade not null,
  topic_a           uuid references topics(id) on delete cascade not null,
  topic_b           uuid references topics(id) on delete cascade not null,
  relation_strength float check (relation_strength between 0.0 and 1.0),
  created_at        timestamp with time zone default now()
);

alter table topic_relations enable row level security;

create policy "topic_relations: users own their rows"
  on topic_relations for all
  using  (user_id = auth.uid())
  with check (user_id = auth.uid());

-- ── Classrooms ────────────────────────────────────────────────
-- Phase 11. No user_id column — instructor_id plays that role.
create table if not exists classrooms (
  id             uuid primary key default gen_random_uuid(),
  instructor_id  uuid references auth.users(id) on delete cascade not null,
  name           text not null,
  created_at     timestamp with time zone default now()
);

alter table classrooms enable row level security;

create policy "classrooms: instructors own their classrooms"
  on classrooms for all
  using  (instructor_id = auth.uid())
  with check (instructor_id = auth.uid());

-- ── Classroom Members ─────────────────────────────────────────
-- Phase 11.
create table if not exists classroom_members (
  classroom_id  uuid references classrooms(id) on delete cascade,
  student_id    uuid references auth.users(id) on delete cascade,
  primary key (classroom_id, student_id)
);

alter table classroom_members enable row level security;

-- Students can see their own membership; instructors can see all members of
-- their classroom. This is the minimal policy needed for Phase 11.
create policy "classroom_members: students see own membership"
  on classroom_members for select
  using (student_id = auth.uid());

create policy "classroom_members: instructors manage their classroom"
  on classroom_members for all
  using (
    exists (
      select 1 from classrooms c
      where c.id = classroom_members.classroom_id
        and c.instructor_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from classrooms c
      where c.id = classroom_members.classroom_id
        and c.instructor_id = auth.uid()
    )
  );

-- ── Indexes ───────────────────────────────────────────────────
-- Speeds up the most common queries per user
create index if not exists idx_topics_user_id            on topics(user_id);
create index if not exists idx_debate_rounds_user_id     on debate_rounds(user_id);
create index if not exists idx_debate_rounds_topic_id    on debate_rounds(topic_id);
create index if not exists idx_mastery_state_user_id     on mastery_state(user_id);
create index if not exists idx_mastery_state_next_review on mastery_state(next_review_due);
create index if not exists idx_topic_relations_user_id   on topic_relations(user_id);

-- Phase 5 will add an ivfflat or hnsw index on debate_rounds.embedding
-- once the pgvector similarity search is wired up.
