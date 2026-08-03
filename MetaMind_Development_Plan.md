# MetaMind — Technical Development Plan (v4)

## 1. What the System Does

MetaMind is an AI-driven study companion that measures **understanding**, not recall. Instead of quizzing you with flashcards, it makes you *explain* a concept in your own words, then generates the sharpest fair counterargument or edge-case challenge against your explanation. Your ability to defend or fail to defend your explanation becomes the signal that drives a personalized, adaptive spaced-repetition schedule — topics you only *think* you understand get resurfaced sooner than a normal recall-based system would catch.

A lightweight gamification layer keeps the loop motivating enough to use daily through a semester. The platform serves three distinct age groups through one shared engine with different skins, a second LLM agent handles calendar scheduling, a set of pedagogical/technical enhancements extend the core loop, and every AI interaction follows a transparent, step-by-step narration so the student is never blindsided by a challenge or a score.

**Core loop, in one sentence:** Explain → the agent narrates what it understood and what kind of challenge is coming → challenge → defend or fail → the agent narrates its scoring criteria before revealing the score → system remembers exactly where you're weak → system decides when to bring it back — with a planner agent deciding *when in your actual week* that happens.

---

## 2. How It Works — Conceptual Flow

```
Student explains a topic
        │
        ▼
Student predicts their own score first (confidence calibration, 10.1)
        │
        ▼
Backend fetches memory:
  - past mastery record for this topic
  - similar past struggles (semantic search across ALL topics, scoped to this user only)
  - verified reference material for this topic (for grounding, Section 6)
  - recent low-score streak on this topic (for frustration-aware pacing, 10.6)
        │
        ▼
Backend builds a prompt with that context + student's explanation
        │
        ▼
Debate Agent (generation call, Section 11) returns, in order:
  - ACKNOWLEDGE what it understood
  - LOCATE which part of the topic it will test
  - CLASSIFY what kind of challenge is coming
  - PRESENT the actual challenge
        │
        ▼
Student responds to the challenge
        │
        ▼
Scoring Agent (separate call, Section 11) returns, in order:
  - CRITERIA it checked for
  - VERDICT (held up / partial / failed)
  - SCORE, failure mode, weak point
        │
        ▼
Student writes a one-sentence compression summary of what they learned (10.3)
        │
        ▼
Backend updates mastery_state + schedules next review date (deterministic)
        │
        ▼
Separate Planner LLM negotiates WHEN that review happens against
real calendar free time + exam dates (Section 9)
        │
        ▼
Dashboard shows mastery trend, streaks, knowledge map, what's due next, proposed schedule
```

The LLMs are **stateless** — they know nothing between calls. All "memory" lives in the database. The backend's entire job is deciding what to retrieve and inject into the prompt before every call.

---

## 3. Architecture

**Three-tier system, two specialized LLM agents (each split into a generation call and a scoring call), plus optional multi-modal input paths:**

| Layer | Tech | Responsibility |
|---|---|---|
| Frontend | React | Explanation input (text/voice/sketch), debate thread UI showing each narrated step, mastery dashboard, streaks/badges, knowledge map, mode-specific theming |
| Backend | FastAPI | Memory retrieval, prompt assembly, LLM calls, scheduler, scoring, auth enforcement, pacing logic |
| Data | Supabase (Postgres + pgvector) | Structured memory, semantic memory, auth, row-level security |
| Debate Agent — Generation | LLM API (Claude) | Produces the acknowledge/locate/classify/present sequence, grounded in retrieved course material |
| Debate Agent — Scoring | LLM API (Claude, separate call) | Produces the criteria/verdict/score/failure-mode sequence |
| Planner Agent | LLM API (separate call) | Negotiates a study calendar from real free/busy data + review-due dates |
| Embeddings | Embedding API | Vector embeddings for semantic memory and knowledge map edges |
| Speech-to-Text | STT API | Converts voice explanations to text before entering the same pipeline |
| OCR | Vision/OCR API | Extracts text from photographed notes/slides into reference material |

**Why this shape:** the frontend never talks to any LLM directly. Generation and scoring are always separate calls — narrower prompts drift less and let each stage narrate its own reasoning without the other stage's job leaking in. Multi-modal inputs (voice, photo) are converted to plain text *before* entering the pipeline, so the core debate/scoring logic never needs to know how the input arrived.

### Three layers of memory

1. **Short-term** — the current debate thread, now including each narrated step (acknowledge/locate/classify/present, then criteria/verdict/score) as distinct visible messages
2. **Long-term structured** — `mastery_state` per topic: score, failure mode, weak point, next review date, low-score streak
3. **Long-term semantic** — embeddings of past explanations, searched via pgvector, scoped to the current user, also used to derive knowledge map edges (10.4)

---

## 4. Frontend: Three Modes, One Engine

| Mode | Age | Framing | Tone example |
|---|---|---|---|
| 🎨 Kids | ~8–12 | "Boss battle" with a character companion | *"Here's what I noticed... here's the part I want to poke at..."* |
| ⚡ Teen | ~13–17 | "Prove me wrong" — witty rival, opt-in friend leaderboards | *"Bold claim. Here's what I'm testing, and here's how."* |
| 🎓 Adult | 18+ | Rigorous debate partner, data-forward dashboard | *"Testing your claim against the boundary condition here."* |

**Implementation:**
- React theme provider supplying design tokens per mode
- Copy dictionary replacing hardcoded strings per mode
- `tone` parameter threaded into the Debate Agent's generation prompt (Section 11) so rigor/vocabulary shifts with mode — but the four-step narration structure itself never changes, only its wording
- Backend data model stays identical across modes
- Voice input (10.7) is especially valuable in Kids Mode

**Production note:** real deployment to minors would need parental-consent flows and COPPA-style handling — out of scope to fully implement, worth naming as a design consideration.

---

## 5. Security & Privacy

- **Supabase Auth + Row-Level Security** on every table — a user can only read/write rows where `user_id = auth.uid()`
- **Parent/guardian accounts** in Kids Mode, linked to but distinct from the child's account
- **Data minimization** — nickname/avatar over real names in Kids Mode; no unnecessary metadata stored
- **API hardening** — `user_id` always derived from verified JWT; rate limiting on debate, calendar, and instructor-dashboard endpoints; Pydantic validation everywhere; CORS locked to the real frontend domain
- **Secrets** — LLM keys and Supabase service-role key live only in backend environment variables
- **Encryption** — HTTPS everywhere, Postgres encryption at rest by default; field-level encryption on `student_explanation` as a stretch goal
- **Prompt injection defense** — retrieval logic lives entirely in backend code, never derived from LLM output or raw user text
- **Cross-user leakage prevention** — every pgvector similarity query must filter by `user_id`
- **Instructor dashboard privacy** (10.11) — aggregation happens server-side; individual `student_explanation` text is never exposed to the instructor view
- **Logging** — auth failures and rate-limit hits logged; full explanation text avoided in server logs

---

## 6. Hallucination Mitigation

- **RAG grounding** — course notes/textbook excerpts embedded per topic in `reference_material`; retrieved chunk injected before every counterargument is generated
- **Source-grounded output** — the Debate Agent's LOCATE step (Section 11) forces it to explicitly name which part of the reference material it's drawing from, which doubles as a built-in grounding check
- **Narrow, split calls** — generation and scoring are always separate LLM calls (Section 11)
- **Fact-check pass** — a second cheap call flags unsupported claims before anything reaches the student
- **Human-in-the-loop** — students can flag a counterargument as wrong (`/debate/{id}/flag`)
- **Honesty constraint in prompt** — explicit instruction to say "I'm not certain" rather than assert unsupported claims
- **Temperature control** — lower for scoring, slightly higher (still RAG-grounded) for generation
- **Reverse-role mode** (10.2) reuses this same grounding — the backend specifies exactly one planted error; the agent is never asked to invent an error freely

---

## 7. Database Schema (Supabase / Postgres)

```sql
-- All tables include RLS policies scoping rows to auth.uid() = user_id

create table topics (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id),
  name text not null,
  course text,
  created_at timestamp default now()
);

create table reference_material (
  id uuid primary key default gen_random_uuid(),
  topic_id uuid references topics(id),
  content text,
  source_type text default 'text', -- 'text' | 'ocr_scan'
  embedding vector(1536),
  created_at timestamp default now()
);

create table debate_rounds (
  id uuid primary key default gen_random_uuid(),
  topic_id uuid references topics(id),
  user_id uuid references auth.users(id),
  round_type text default 'standard', -- 'standard' | 'reverse_role'
  input_mode text default 'text',     -- 'text' | 'voice' | 'sketch'
  student_explanation text,
  predicted_score float,              -- confidence calibration, 10.1

  -- Debate Agent generation output (Section 11)
  acknowledgment text,
  focus_area text,
  challenge_type text,                -- edge_case | counterexample | boundary_condition | new_context
  challenge text,

  student_rebuttal text,
  compression_summary text,           -- 10.3

  -- Debate Agent scoring output (Section 11)
  scoring_criteria text,
  verdict text,                       -- held_up | partial | failed
  mastery_score float,
  failure_mode text,
  weak_point text,

  flagged_incorrect boolean default false,
  embedding vector(1536),
  created_at timestamp default now()
);

create table mastery_state (
  topic_id uuid primary key references topics(id),
  user_id uuid references auth.users(id),
  current_score float,
  last_reviewed timestamp,
  next_review_due timestamp,
  total_attempts int default 0,
  low_score_streak int default 0     -- drives frustration-aware pacing, 10.6
);

create table streaks (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id),
  current_streak int default 0,
  longest_streak int default 0,
  freeze_tokens int default 0,        -- 10.5
  last_active_date date
);

create table achievements (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id),
  topic_id uuid references topics(id),
  type text,
  earned_at timestamp default now()
);

create table exam_dates (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id),
  course text,
  exam_date date,
  created_at timestamp default now()
);

create table scheduled_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id),
  topic_id uuid references topics(id),
  proposed_time timestamp,
  status text default 'proposed',
  rationale text,
  created_at timestamp default now()
);

create table topic_relations (
  -- knowledge map edges, 10.4
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id),
  topic_a uuid references topics(id),
  topic_b uuid references topics(id),
  relation_strength float,
  created_at timestamp default now()
);

create table classrooms (
  -- instructor aggregate dashboard, 10.11
  id uuid primary key default gen_random_uuid(),
  instructor_id uuid references auth.users(id),
  name text,
  created_at timestamp default now()
);

create table classroom_members (
  classroom_id uuid references classrooms(id),
  student_id uuid references auth.users(id),
  primary key (classroom_id, student_id)
);
```

---

## 8. API Endpoints Needed (FastAPI)

| Endpoint | Method | Purpose |
|---|---|---|
| `/topics` | GET / POST | List / create topics |
| `/topics/{id}/reference` | POST | Upload verified course material (text or photo → OCR, 10.10) |
| `/debate/start` | POST | Submit an explanation (text/voice/sketch); runs the Debate Agent generation call |
| `/debate/respond` | POST | Submit a rebuttal; runs the Debate Agent scoring call |
| `/debate/{id}/flag` | POST | Flag a counterargument as incorrect |
| `/debate/reverse/start` | POST | Start a reverse-role round (10.2) |
| `/debate/{id}/compress` | POST | Submit a one-sentence compression summary (10.3) |
| `/dashboard` | GET | Mastery scores, what's due, streak info, calibration accuracy |
| `/scheduler/due` | GET | Topics due for review today |
| `/streaks` | GET | Current streak, longest streak, freeze tokens |
| `/streaks/freeze` | POST | Spend a freeze token to protect a streak |
| `/achievements` | GET | Unlocked badges/milestones |
| `/knowledge-map` | GET | Topic relation graph for visualization (10.4) |
| `/cheatsheet` | GET | Auto-compiled study sheet from current weak points (10.8) |
| `/topics/{id}/diff` | GET | Compare first vs. latest explanation for a topic (10.9) |
| `/calendar/connect` | POST | OAuth flow to link Google Calendar |
| `/calendar/generate` | POST | Trigger Planner LLM to propose this week's schedule |
| `/calendar/sessions` | GET / PATCH | View / accept / reschedule / skip proposed sessions |
| `/classroom/{id}/dashboard` | GET | Instructor aggregate view, no individual explanations exposed (10.11) |

---

## 9. The Planner Agent (Calendar)

```
Debate Agent  ──▶  mastery_state, next_review_due  (deterministic, rule-based)
                          │
                          ▼
              ┌───────────────────────┐
              │   Planner LLM Agent    │
              └───────────────────────┘
                          ▲
                          │
        Google Calendar freebusy API  ───┘
        exam_dates (student-entered)  ───┘
```

- Pulls topics due this week, real free/busy blocks, upcoming exam dates
- Generates a proposed schedule with a short rationale
- **Grounding rule:** never invents a time slot — must select from real free/busy blocks the backend fetched; backend validates every `proposed_time` falls inside a real free block before saving, else reject and regenerate
- **Follow-up enhancement:** the Planner Agent should follow the same transparent-narration principle as Section 11 — state which topics it considered, why it prioritized what it did, before presenting the proposed schedule. Worth writing as its own explicit prompt once Phase 9 begins.

---

## 10. Advanced Features Deep Dive

### 10.1 Confidence Calibration
Student predicts their own score (`predicted_score`) before the Scoring Agent reveals its verdict. Dashboard shows a calibration curve over time — consistently over- or under-confident. A second, independent signal of learning quality beyond raw mastery.

### 10.2 Reverse-Role "Catch the Error" Mode
The Debate Agent deliberately alters one specific fact from the grounded reference material and presents it as its own explanation; student finds and corrects the flaw. The backend specifies the exact planted error — the agent never invents an error freely, which keeps this mode from becoming an actual hallucination risk.

### 10.3 Compression Step
After a round resolves, the student writes a one-sentence summary of what they learned (`compression_summary`). Backed by retrieval-practice / testing-effect learning science.

### 10.4 Knowledge Map
Using embeddings already computed for semantic memory, compute pairwise similarity between topics' weak points and store meaningful connections in `topic_relations`. Rendered as a graph — a living map of the student's actual prerequisite structure.

### 10.5 Streak Freeze Tokens
Earned periodically, spendable to protect a streak through a legitimate day off.

### 10.6 Frustration-Aware Pacing
`low_score_streak` increments on consecutive low scores for a topic. Past a threshold, the Debate Agent's CLASSIFY step (Section 11) favors gentler challenge types until a score recovers.

### 10.7 Voice Input
Speech-to-text conversion before entering the same pipeline as typed input (`input_mode = 'voice'`). Especially valuable in Kids Mode.

### 10.8 Personalized Cheat Sheet Generator
Pulls all current `weak_point` entries across topics due soon or exam-relevant, compiles a single-page study sheet targeting only genuine gaps.

### 10.9 Explanation Diffing
Side-by-side comparison of a student's first attempt at a topic vs. their latest, pulled from existing `debate_rounds` history.

### 10.10 OCR Ingestion for Reference Material
Photograph a textbook page or slide; OCR extracts text into `reference_material` (`source_type = 'ocr_scan'`), feeding the same grounding pipeline as manually typed notes.

### 10.11 Instructor Aggregate Dashboard
Aggregates `mastery_state` and `weak_point` frequency across a classroom without ever exposing individual `student_explanation` text — useful insight for a teacher, without individual surveillance.

---

## 11. Prompt Design — Transparent Debate & Scoring Agents

This is the core design principle that keeps the student from ever being blindsided: **the agent narrates before it challenges, and narrates before it scores.** Generation and scoring stay as two separate calls (Section 6), each following its own fixed, unskippable sequence.

### 11.1 Debate Agent — Generation Call

```
You are the Debate Agent for MetaMind, an educational tool that tests whether 
a student truly understands a concept — not whether they can recall it.

Your defining trait: you are never opaque. The student should always 
understand exactly why you're asking what you're asking, before you ask it. 
A challenge that comes "out of nowhere" is a failure on your part, regardless 
of how sharp it is.

<context>
Topic: {topic_name}
Reference material (verified, grounded source — do not go beyond this): {reference_chunk}
Student's past performance on this topic: {mastery_summary}
Related past struggles on other topics: {related_struggles}
Mode: {mode}  -- one of: kids | teen | adult
Round type: {round_type}  -- one of: standard | reverse_role
Recent low-score streak on this topic: {low_score_streak}
</context>

<required_process>
Follow these steps, in this exact order, every time:

1. ACKNOWLEDGE — in one sentence, restate what you understood from the 
   student's explanation.

2. LOCATE — name plainly which part of the topic or reference material your 
   challenge will focus on.

3. CLASSIFY — tell the student what kind of challenge is coming, before 
   giving it. Choose one and name it explicitly: edge case, counterexample, 
   boundary condition, or application in a new context.

4. PRESENT — now give the actual challenge.

Do not skip or reorder these steps. Do not merge them into one sentence — 
each should be clearly separated so the student can follow your reasoning 
in real time.
</required_process>

<reverse_role_adjustment>
If round_type is "reverse_role": you are not challenging the student's 
explanation. Instead, you present your OWN explanation of the topic, 
containing exactly one planted error: {planted_error}. Adapt the process:
1. ACKNOWLEDGE the topic you're about to explain
2. LOCATE which part of the topic your explanation will cover
3. CLASSIFY what general kind of thing to watch for, WITHOUT naming the 
   specific error
4. PRESENT your explanation, containing exactly the one planted error and 
   nothing else incorrect
Never introduce an error beyond {planted_error}. Every other claim must be 
fully grounded in {reference_chunk}.
</reverse_role_adjustment>

<grounding_rules>
- Every factual claim must trace back to {reference_chunk}.
- If you are not confident something is supported by the reference material, 
  say so explicitly rather than presenting it as fact.
- Never invent details about the student's history beyond what's provided.
</grounding_rules>

<tone_by_mode>
- kids: warm, curious, simple vocabulary — still complete all 4 steps
- teen: witty, a little competitive, still complete all 4 steps
- adult: direct, precise, minimal warmth — still complete all 4 steps
</tone_by_mode>

<pacing_adjustment>
If low_score_streak >= 3: soften the CLASSIFY step to a gentler challenge 
type (favor "boundary condition" over "counterexample"), and add one 
encouraging clause in ACKNOWLEDGE. Still complete all steps in full — 
pacing changes difficulty, never transparency.
</pacing_adjustment>

<output_format>
Return only this JSON structure, nothing else:
{
  "acknowledgment": "...",
  "focus_area": "...",
  "challenge_type": "edge_case | counterexample | boundary_condition | new_context",
  "challenge": "..."
}
</output_format>
```

### 11.2 Debate Agent — Scoring Call

```
You are the Scoring Agent for MetaMind. You do not generate challenges — you 
only assess how well a student's response held up, and you must show your 
reasoning, not just output a number.

<context>
Topic: {topic_name}
Reference material: {reference_chunk}
Student's original explanation: {student_explanation}
The challenge presented: {challenge}
Student's response to the challenge: {student_rebuttal}
</context>

<required_process>
1. CRITERIA — state plainly, in one sentence, what you were checking for in 
   the student's response (tie this directly to the challenge_type from the 
   generation step).
2. VERDICT — did the response hold up, partially hold up, or fail? Say which, 
   and why, in plain terms — no jargon-only justifications.
3. SCORE — a 0.0–1.0 mastery score, consistent with the verdict above.
4. FAILURE MODE — if score < 0.7, classify as one of: 
   shallow_memorization | wrong_mental_model | correct_but_unclear | 
   partial_gap
5. WEAK POINT — a short, specific phrase describing exactly what to review 
   next time.
</required_process>

<grounding_rules>
- Base your verdict only on {reference_chunk} — do not introduce outside 
  facts not present in the provided material.
- If the reference material is ambiguous on a point the student raised, 
  say so rather than scoring against an assumption.
</grounding_rules>

<output_format>
Return only this JSON structure:
{
  "criteria": "...",
  "verdict": "held_up | partial | failed",
  "mastery_score": 0.0,
  "failure_mode": "...",
  "weak_point": "..."
}
```

### 11.3 Why this design solves "not blindsided"

The student-facing thread reconstructs `acknowledgment → focus_area → challenge_type → challenge` as separate visible messages, not one wall of text — the agent reads as genuinely walking the student through its thinking. The scoring side mirrors this in reverse: `criteria → verdict → score` means the student always sees *why* they got a score before seeing the number itself, which matters for how a score lands emotionally.

---

## 12. Phase-Wise Development Plan

### Phase 1 — Core Loop (Weeks 1–2)
- Supabase Auth + RLS from day one
- `topics`, `debate_rounds` tables; FastAPI skeleton; barebones Adult-mode UI
- Implement a first, simplified version of the Section 11 generation prompt (plain text output is fine here — structured JSON comes in Phase 2)
- **Milestone:** does the loop produce genuinely sharp, relevant counterarguments?

### Phase 2 — Structured Scoring, Narration, Calibration + Compression (Weeks 3–4)
- Implement the full Section 11 prompts as JSON-structured calls (generation and scoring, separately)
- Wire the four-step narration and five-step scoring sequence into the frontend as distinct visible messages, not a single block of text
- Add `predicted_score` capture (10.1) and `compression_summary` capture (10.3)
- **Milestone:** does the student see the acknowledge/locate/classify/present sequence clearly *before* the challenge, and criteria/verdict clearly *before* the score? Does the calibration gap look sensible on test data?

### Phase 3 — Scheduler (Weeks 5–6)
- Rule-based scheduler using `next_review_due`
- **Milestone:** does it correctly resurface genuinely weak topics first?

### Phase 4 — Grounding & Hallucination Mitigation (Weeks 7–8)
- `reference_material` table, RAG retrieval before generation calls
- Fact-check pass, `/debate/{id}/flag`
- Verify the Section 11 LOCATE step is actually pulling from real retrieved chunks, not just claiming to
- **Milestone:** does grounding measurably reduce unsupported claims?

### Phase 5 — Semantic Memory + Knowledge Map (Weeks 9–10)
- Embeddings on `debate_rounds`, pgvector similarity search scoped to `user_id`
- `topic_relations` (10.4), `/knowledge-map` endpoint + graph visualization
- **Milestone:** does the AI reference a different topic's past weak point, and does the knowledge map graph look meaningfully structured?

### Phase 6 — Security Hardening Pass (Week 11)
- Full RLS audit, rate limiting, secrets audit, parent/child separation if demoing Kids Mode
- **Milestone:** can you demonstrate one account cannot read another's data even via a crafted request?

### Phase 7 — Three-Mode Frontend + Gamification (Weeks 12–13)
- Theme provider, copy dictionary, `tone` parameter feeding into Section 11's tone_by_mode block
- `streaks`, `achievements`, freeze tokens (10.5)
- **Milestone:** does switching modes change both visuals and narration wording, while the four-step/five-step structure itself stays intact?

### Phase 8 — Advanced Pedagogical Modes (Week 14)
- Reverse-role mode (10.2) using the reverse_role_adjustment block from Section 11.1
- Frustration-aware pacing (10.6) using the pacing_adjustment block
- **Milestone:** does reverse-role mode ever accidentally introduce an error beyond the one the backend specified?

### Phase 9 — Planner Agent & Calendar (Weeks 15–16)
- Google Calendar OAuth, `exam_dates`, `scheduled_sessions`
- Planner LLM grounded strictly in real free/busy data, with the same transparent-narration principle applied (Section 9's follow-up enhancement)
- **Milestone:** does a proposed schedule ever fall outside real free time?

### Phase 10 — Accessibility & Ingestion Extensions (Week 17, if time permits)
- Voice input (10.7), OCR ingestion (10.10), cheat sheet generator (10.8), explanation diffing (10.9)
- **Milestone:** can a student populate an entire topic's reference material from a photographed textbook page with no manual typing?

### Phase 11 — Instructor Dashboard (Week 18, if time permits)
- `classrooms`, `classroom_members`, aggregate-only dashboard endpoint (10.11)
- **Milestone:** can you prove the instructor view never returns individual explanation text — only aggregates?

### Phase 12 — Polish, Dogfooding, Report (Final Weeks)
- Daily use on real coursework for genuine demo data
- Write up core contributions: argument-based mastery estimation, transparent multi-step agent narration, three-layer memory + knowledge map, dual-agent grounding, security-by-design, metacognitive calibration tracking, privacy-preserving aggregate insight
- Strongest demo moments: the narrated challenge sequence itself, mode-switching, knowledge map graph, calibration curve, reverse-role mode, planner agent negotiation

### Stretch Goal
- Replace the rule-based scheduler with a bandit/RL-style policy learning personal review-interval sensitivity from `mastery_score` trends over time

---

## 13. Suggested Stack Summary

- **Frontend:** React (theme-provider architecture, graph visualization library for the knowledge map, e.g. D3 or a force-directed graph component)
- **Backend:** FastAPI (Python)
- **Database/Auth:** Supabase (Postgres + pgvector + Auth + RLS)
- **Debate Agent:** Claude API, split into generation and scoring calls (Section 11), grounded via RAG, supports standard and reverse-role prompt modes
- **Planner Agent:** Claude API, separate calls, grounded against real Google Calendar free/busy data
- **Embeddings:** text-embedding API (e.g. OpenAI `text-embedding-3-small`)
- **Speech-to-Text:** for voice input mode
- **OCR/Vision API:** for photographed reference material ingestion
- **Calendar integration:** Google Calendar API (freebusy endpoint)
- **Scheduler:** plain Python logic (Phase 3), optionally upgraded to a bandit algorithm (stretch goal)

---

## Note on Scope

Phases 1–9 (Weeks 1–16) constitute the core, demoable system and match a standard semester timeline. Phases 10–11 are explicitly marked "if time permits" — pull them forward only if an earlier phase finishes ahead of schedule. Treat the milestone checks as honest go/no-go gates rather than rushing through them to reach later phases.
