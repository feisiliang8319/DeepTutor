-- A page session belongs to one issued exam, never to browser storage.
CREATE TABLE exam_integrity (
 set_id TEXT PRIMARY KEY REFERENCES formal_exams(set_id),
 session_hash TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('active','sealed','invalidated')),
 started_at REAL NOT NULL, last_seen REAL NOT NULL,
 ended_at REAL, reason TEXT,
 retake_authorized_by TEXT, retake_authorized_at REAL
);
CREATE TABLE exam_integrity_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 set_id TEXT NOT NULL REFERENCES formal_exams(set_id),
 kind TEXT NOT NULL, actor_id TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TRIGGER exam_integrity_events_no_update BEFORE UPDATE ON exam_integrity_events BEGIN SELECT RAISE(ABORT,'exam integrity events are append-only'); END;
CREATE TRIGGER exam_integrity_events_no_delete BEFORE DELETE ON exam_integrity_events BEGIN SELECT RAISE(ABORT,'exam integrity events are append-only'); END;
