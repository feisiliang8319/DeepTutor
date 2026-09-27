-- A learner may leave an unsubmitted optional exercise without claiming it
-- was completed. Keep the issued set for audit; never remove saved answers.
ALTER TABLE task_sets ADD COLUMN skipped_at TEXT;
DROP INDEX uq_task_sets_one_open_per_course;
CREATE UNIQUE INDEX uq_task_sets_one_open_per_course
  ON task_sets (learner_id, course_version_id)
  WHERE submitted_at IS NULL AND skipped_at IS NULL;
