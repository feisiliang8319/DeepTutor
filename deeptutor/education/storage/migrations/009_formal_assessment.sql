-- Formal assessments reuse immutable attempts and append-only submissions.
CREATE TABLE academic_background (
 learner_id TEXT PRIMARY KEY REFERENCES learner_profiles(id),
 school_grade INTEGER CHECK(school_grade BETWEEN 1 AND 13), updated_by TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE assessment_courses (
 course_version_id TEXT PRIMARY KEY REFERENCES course_versions(id),
 curriculum_key TEXT NOT NULL, grade INTEGER NOT NULL CHECK(grade BETWEEN 1 AND 12),
 units_json TEXT NOT NULL, configured_by TEXT NOT NULL, configured_at TEXT NOT NULL,
 competition_domain TEXT CHECK(competition_domain IN ('mathematics','science','technology','engineering'))
);
CREATE TABLE assessment_item_tags (
 item_id TEXT PRIMARY KEY REFERENCES assessment_items(id),
 unit_id TEXT NOT NULL, tier TEXT NOT NULL CHECK(tier IN ('A','B','C')),
 bank TEXT NOT NULL CHECK(bank IN ('regular','competition')),
 core INTEGER NOT NULL CHECK(core IN (0,1)), points INTEGER NOT NULL CHECK(points BETWEEN 1 AND 100),
 family_key TEXT NOT NULL
);
CREATE TABLE subject_placements (
 learner_id TEXT NOT NULL REFERENCES learner_profiles(id), subject_key TEXT NOT NULL, curriculum_key TEXT NOT NULL,
 grade INTEGER NOT NULL CHECK(grade BETWEEN 1 AND 13), entry_level TEXT NOT NULL CHECK(entry_level IN ('foundation','standard','extension')),
 revision INTEGER NOT NULL DEFAULT 1, updated_by TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(learner_id,subject_key,curriculum_key)
);
CREATE TABLE formal_exams (
 set_id TEXT PRIMARY KEY REFERENCES task_sets(id), learner_id TEXT NOT NULL REFERENCES learner_profiles(id),
 course_version_id TEXT NOT NULL REFERENCES course_versions(id), subject_key TEXT NOT NULL, curriculum_key TEXT NOT NULL,
 grade INTEGER NOT NULL, placement_revision INTEGER NOT NULL, placement_grade INTEGER NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('checkin','daily','unit','final','promotion','competition')),
 unit_id TEXT, deadline REAL NOT NULL, snapshot_json TEXT NOT NULL,
 result_json TEXT, result_revision INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE exam_drafts (set_id TEXT PRIMARY KEY REFERENCES formal_exams(set_id), answers_json TEXT NOT NULL, revision INTEGER NOT NULL, saved_at REAL NOT NULL);
CREATE TABLE exam_score_reviews (
 id INTEGER PRIMARY KEY AUTOINCREMENT, set_id TEXT NOT NULL REFERENCES formal_exams(set_id), item_id TEXT NOT NULL,
 points REAL NOT NULL CHECK(points>=0), note TEXT NOT NULL, reviewer_id TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TRIGGER exam_score_reviews_no_update BEFORE UPDATE ON exam_score_reviews BEGIN SELECT RAISE(ABORT,'exam score reviews are append-only'); END;
CREATE TRIGGER exam_score_reviews_no_delete BEFORE DELETE ON exam_score_reviews BEGIN SELECT RAISE(ABORT,'exam score reviews are append-only'); END;
CREATE TABLE promotion_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, set_id TEXT NOT NULL UNIQUE REFERENCES formal_exams(set_id),
 learner_id TEXT NOT NULL, subject_key TEXT NOT NULL, curriculum_key TEXT NOT NULL,
 from_grade INTEGER NOT NULL, to_grade INTEGER NOT NULL, actor_id TEXT NOT NULL,
 evidence_json TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TRIGGER promotion_events_no_update BEFORE UPDATE ON promotion_events BEGIN SELECT RAISE(ABORT,'promotion events are append-only'); END;
CREATE TRIGGER promotion_events_no_delete BEFORE DELETE ON promotion_events BEGIN SELECT RAISE(ABORT,'promotion events are append-only'); END;
CREATE TABLE placement_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, learner_id TEXT NOT NULL, subject_key TEXT NOT NULL, curriculum_key TEXT NOT NULL,
 grade INTEGER NOT NULL, actor_id TEXT NOT NULL, source TEXT NOT NULL, created_at REAL NOT NULL
);

CREATE INDEX formal_exams_learner ON formal_exams(learner_id,subject_key,curriculum_key,grade);
CREATE TRIGGER placement_events_no_update BEFORE UPDATE ON placement_events BEGIN SELECT RAISE(ABORT,'placement events are append-only'); END;
CREATE TRIGGER placement_events_no_delete BEFORE DELETE ON placement_events BEGIN SELECT RAISE(ABORT,'placement events are append-only'); END;
