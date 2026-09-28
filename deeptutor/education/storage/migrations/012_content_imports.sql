-- Import receipts never grant content approval or change learner evidence.
CREATE TABLE content_imports (
 id TEXT PRIMARY KEY, course_version_id TEXT NOT NULL REFERENCES course_versions(id),
 source_name TEXT NOT NULL, actor_id TEXT NOT NULL, imported_at TEXT NOT NULL,
 inserted INTEGER NOT NULL, skipped INTEGER NOT NULL, receipt_json TEXT NOT NULL
);
CREATE TABLE content_reviews (
 id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL REFERENCES assessment_items(id),
 content_hash TEXT NOT NULL, actor_id TEXT NOT NULL, decision TEXT NOT NULL,
 note TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TRIGGER content_reviews_no_update BEFORE UPDATE ON content_reviews
BEGIN SELECT RAISE(ABORT,'content reviews are append-only'); END;
CREATE TRIGGER content_reviews_no_delete BEFORE DELETE ON content_reviews
BEGIN SELECT RAISE(ABORT,'content reviews are append-only'); END;
