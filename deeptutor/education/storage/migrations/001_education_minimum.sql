-- 001_education_minimum.sql
-- P0 minimal Education Data Layer schema. Mirrors docs/P0-DESIGN.md §2
-- field-for-field; do not add/remove columns here without updating that
-- document first (it is the design SSoT, this file is the executable copy).
--
-- Applied by deeptutor.education.storage.sqlite.apply_migration, which
-- wraps the whole file in one manual transaction and rolls back completely
-- if the post-apply trigger-integrity check fails (P0-DESIGN.md §2.5
-- "迁移后置断言"). IF NOT EXISTS on every statement makes re-running this
-- file a no-op (P0-DESIGN.md §6 test #10).
--
-- Append-only enforcement: student_attempts and judgment_records each get a
-- BEFORE UPDATE and a BEFORE DELETE trigger that RAISE(ABORT). That is four
-- triggers total; deeptutor.education.storage.sqlite.REQUIRED_TRIGGERS is
-- the single source of truth for that count and must be kept in sync with
-- the trigger names below.

CREATE TABLE IF NOT EXISTS learner_profiles (
  id                 TEXT PRIMARY KEY,
  deep_tutor_user_id TEXT NOT NULL UNIQUE,
  display_name       TEXT NOT NULL,
  grade_band         TEXT,
  locale             TEXT NOT NULL DEFAULT 'en-US',
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS courses (
  id          TEXT PRIMARY KEY,
  subject_key TEXT NOT NULL,
  title       TEXT NOT NULL,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS course_versions (
  id           TEXT PRIMARY KEY,
  course_id    TEXT NOT NULL REFERENCES courses(id),
  version      TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  status       TEXT NOT NULL CHECK (status IN ('draft','active','archived')),
  created_at   TEXT NOT NULL,
  UNIQUE (course_id, version)
);

CREATE TABLE IF NOT EXISTS knowledge_nodes (
  id                TEXT PRIMARY KEY,
  course_version_id TEXT NOT NULL REFERENCES course_versions(id),
  code              TEXT NOT NULL,
  node_type         TEXT NOT NULL,
  title             TEXT NOT NULL,
  sort_order        INTEGER NOT NULL,
  -- External curriculum-standard anchor (CCSS '4.OA.B.4', AP CED topic id, …).
  -- Nullable on purpose: the schema is not math-specific and self-authored or
  -- cross-standard nodes have no single code — NULL means "not anchored", not
  -- "to be filled in". Deliberately not UNIQUE: one published standard is
  -- routinely split into several independently-diagnosable nodes (4.OA.B.4 →
  -- factor pairs / multiples / prime-composite), so many-to-one is the norm.
  standard_code     TEXT,
  UNIQUE (course_version_id, code)
);

-- Reverse lookup "which nodes cover standard X" is the main query behind any
-- curriculum-coverage audit.
CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_standard_code
  ON knowledge_nodes (course_version_id, standard_code);

CREATE TABLE IF NOT EXISTS knowledge_edges (
  course_version_id TEXT NOT NULL REFERENCES course_versions(id),
  from_node_id      TEXT NOT NULL REFERENCES knowledge_nodes(id),
  to_node_id        TEXT NOT NULL REFERENCES knowledge_nodes(id),
  edge_type         TEXT NOT NULL DEFAULT 'PREREQUISITE',
  PRIMARY KEY (course_version_id, from_node_id, to_node_id, edge_type),
  CHECK (from_node_id <> to_node_id)
);

CREATE TABLE IF NOT EXISTS assessment_items (
  id                    TEXT PRIMARY KEY,
  course_version_id     TEXT NOT NULL REFERENCES course_versions(id),
  knowledge_node_id     TEXT NOT NULL REFERENCES knowledge_nodes(id),
  item_type             TEXT NOT NULL CHECK (item_type IN
                          ('choice','short','numeric','multi_step','visual_model','paper_ref')),
  prompt                TEXT,
  expected_answer       TEXT,
  rubric_json           TEXT,
  difficulty            INTEGER NOT NULL,
  content_scope         TEXT NOT NULL CHECK (content_scope IN
                          ('BUNDLED','PRIVATE_INTERNAL','REFERENCE_ONLY','RESTRICTED')),
  source_ref            TEXT,
  license_note          TEXT,
  attribution_text      TEXT,
  derived_from_item_id  TEXT REFERENCES assessment_items(id),
  reviewer              TEXT,
  reviewed_at           TEXT,
  content_hash          TEXT NOT NULL,
  status                TEXT NOT NULL CHECK (status IN ('candidate','production','retired'))
);

CREATE TABLE IF NOT EXISTS student_attempts (
  id                 TEXT PRIMARY KEY,
  learner_id         TEXT NOT NULL REFERENCES learner_profiles(id),
  assessment_item_id TEXT NOT NULL REFERENCES assessment_items(id),
  knowledge_node_id  TEXT NOT NULL REFERENCES knowledge_nodes(id),
  course_version_id  TEXT NOT NULL REFERENCES course_versions(id),
  response           TEXT NOT NULL,
  is_correct         INTEGER,
  score              REAL,
  started_at         TEXT NOT NULL,
  submitted_at       TEXT NOT NULL,
  duration_ms        INTEGER,
  hint_count         INTEGER NOT NULL DEFAULT 0,
  retry_index        INTEGER NOT NULL DEFAULT 0,
  grader_version     TEXT NOT NULL,
  source             TEXT NOT NULL,
  provenance         TEXT NOT NULL DEFAULT 'native'
                       CHECK (provenance IN ('native','migrated_partial')),
  evidence_strength  TEXT NOT NULL DEFAULT 'system_graded'
                       CHECK (evidence_strength IN
                         ('system_graded','human_reported','hinted','imitated')),
  created_at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attempts_learner_node
  ON student_attempts(learner_id, knowledge_node_id, submitted_at);

CREATE TRIGGER IF NOT EXISTS trg_attempts_no_update
BEFORE UPDATE ON student_attempts
BEGIN SELECT RAISE(ABORT, 'student_attempts is append-only'); END;

CREATE TRIGGER IF NOT EXISTS trg_attempts_no_delete
BEFORE DELETE ON student_attempts
BEGIN SELECT RAISE(ABORT, 'student_attempts is append-only'); END;

CREATE TABLE IF NOT EXISTS judgment_records (
  id             TEXT PRIMARY KEY,
  attempt_id     TEXT NOT NULL REFERENCES student_attempts(id),
  judge_kind     TEXT NOT NULL CHECK (judge_kind IN ('deterministic','llm','human')),
  judge_ref      TEXT NOT NULL,
  prompt_version TEXT,
  rubric_version TEXT,
  verdict        TEXT NOT NULL CHECK (verdict IN ('correct','incorrect','partial','needs_review')),
  confidence     REAL,
  rationale      TEXT,
  created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_judgments_attempt
  ON judgment_records(attempt_id, created_at);

CREATE TRIGGER IF NOT EXISTS trg_judgments_no_update
BEFORE UPDATE ON judgment_records
BEGIN SELECT RAISE(ABORT, 'judgment_records is append-only'); END;

-- P0-DESIGN.md §2.6 only spells out the no-update trigger; the no-delete
-- twin is added here per this task's explicit hard requirement ("BEFORE
-- UPDATE / BEFORE DELETE 触发器") and per §2.5's own "四个触发器" self-check
-- language (two tables x two operations = four). A judgment table that
-- forbids UPDATE but allows DELETE is not actually append-only.
CREATE TRIGGER IF NOT EXISTS trg_judgments_no_delete
BEFORE DELETE ON judgment_records
BEGIN SELECT RAISE(ABORT, 'judgment_records is append-only'); END;

CREATE TABLE IF NOT EXISTS mastery_snapshots (
  learner_id        TEXT NOT NULL REFERENCES learner_profiles(id),
  knowledge_node_id TEXT NOT NULL REFERENCES knowledge_nodes(id),
  score             REAL NOT NULL,
  status            TEXT NOT NULL,
  confidence        REAL,
  policy_version    TEXT NOT NULL,
  last_attempt_id   TEXT REFERENCES student_attempts(id),
  evidence_watermark TEXT,
  updated_at        TEXT NOT NULL,
  PRIMARY KEY (learner_id, knowledge_node_id)
);

CREATE TABLE IF NOT EXISTS review_states (
  learner_id        TEXT NOT NULL REFERENCES learner_profiles(id),
  knowledge_node_id TEXT NOT NULL REFERENCES knowledge_nodes(id),
  stability         REAL NOT NULL,
  difficulty        REAL NOT NULL,
  due_at            TEXT NOT NULL,
  last_review_at    TEXT,
  reps              INTEGER NOT NULL DEFAULT 0,
  lapses            INTEGER NOT NULL DEFAULT 0,
  -- FSRS's own card phase (1=learning, 2=review, 3=relearning) and the
  -- index within the learning/relearning steps. Persisted because they are
  -- not derivable from stability/difficulty: without them every resumed
  -- card silently restarts in the learning phase.
  fsrs_state        INTEGER NOT NULL DEFAULT 1,
  fsrs_step         INTEGER,
  fsrs_params_ver   TEXT NOT NULL,
  PRIMARY KEY (learner_id, knowledge_node_id)
);
