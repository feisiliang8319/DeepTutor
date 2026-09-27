-- Persist the whole validated submission before any external grading call.
CREATE TABLE IF NOT EXISTS task_set_submissions (
    set_id TEXT PRIMARY KEY REFERENCES task_sets(id),
    answers_json TEXT NOT NULL,
    received_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS task_set_submissions_no_update
BEFORE UPDATE ON task_set_submissions BEGIN
    SELECT RAISE(ABORT, 'task_set_submissions is append-only');
END;
CREATE TRIGGER IF NOT EXISTS task_set_submissions_no_delete
BEFORE DELETE ON task_set_submissions BEGIN
    SELECT RAISE(ABORT, 'task_set_submissions is append-only');
END;
