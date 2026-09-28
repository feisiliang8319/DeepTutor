-- Rebuild is executed with FK checks restored and validated by apply_migration.
CREATE TABLE formal_exams_new (
 set_id TEXT PRIMARY KEY REFERENCES task_sets(id), learner_id TEXT NOT NULL REFERENCES learner_profiles(id),
 course_version_id TEXT NOT NULL REFERENCES course_versions(id), subject_key TEXT NOT NULL, curriculum_key TEXT NOT NULL,
 grade INTEGER NOT NULL, placement_revision INTEGER NOT NULL, placement_grade INTEGER NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('checkin','daily','unit','final','promotion','competition','foundation')),
 unit_id TEXT, deadline REAL NOT NULL, snapshot_json TEXT NOT NULL,
 result_json TEXT, result_revision INTEGER NOT NULL DEFAULT 0
);
INSERT INTO formal_exams_new SELECT * FROM formal_exams;
DROP TABLE formal_exams;
ALTER TABLE formal_exams_new RENAME TO formal_exams;
CREATE INDEX formal_exams_learner ON formal_exams(learner_id,subject_key,curriculum_key,grade);
CREATE TABLE competition_foundation_choices (
 competition_set_id TEXT PRIMARY KEY REFERENCES formal_exams(set_id),
 choice TEXT NOT NULL CHECK(choice IN ('yes','no')),
 foundation_set_id TEXT UNIQUE REFERENCES formal_exams(set_id),
 actor_id TEXT NOT NULL, created_at REAL NOT NULL,
 CHECK((choice='yes' AND foundation_set_id IS NOT NULL) OR (choice='no' AND foundation_set_id IS NULL))
);
CREATE TRIGGER competition_foundation_choices_no_update BEFORE UPDATE ON competition_foundation_choices BEGIN SELECT RAISE(ABORT,'foundation choices are append-only'); END;
CREATE TRIGGER competition_foundation_choices_no_delete BEFORE DELETE ON competition_foundation_choices BEGIN SELECT RAISE(ABORT,'foundation choices are append-only'); END;
