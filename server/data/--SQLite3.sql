-- SQLite
-- Delete attendance rows pointing to students that don’t exist
DELETE FROM attendance
WHERE student_id NOT IN (SELECT id FROM students);

--Delete attendance_audit rows pointing to sessions that don’t exist
DELETE FROM attendance_audit
WHERE session_id NOT IN (SELECT id FROM sessions);

--Delete attendance_audit rows pointing to students that don’t exist
DELETE FROM attendance_audit
WHERE student_id NOT IN (SELECT id FROM students);

--Create a new table with FKs, Copy data, Swap tables
CREATE TABLE attendance_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    student_id TEXT NOT NULL,
    first_seen_at TEXT,
    status TEXT NOT NULL DEFAULT 'absent',
    source TEXT,
    first_seen_ts TEXT,
    last_seen_ts TEXT,
    UNIQUE(session_id, student_id),
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (student_id) REFERENCES students(id)
);

--Copy old data → new table
INSERT INTO attendance_new (
    id, session_id, student_id, first_seen_at, status,
    source, first_seen_ts, last_seen_ts
)
SELECT id, session_id, student_id, first_seen_at, status,
       source, first_seen_ts, last_seen_ts
FROM attendance;

--Swap tables
ALTER TABLE attendance RENAME TO attendance_old;
ALTER TABLE attendance_new RENAME TO attendance;

CREATE TABLE attendance_audit_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    student_id TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT NOT NULL,
    reason TEXT,
    actor TEXT,
    ts TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (student_id) REFERENCES students(id)
);

INSERT INTO attendance_audit_new (
    id, session_id, student_id, old_status, new_status,
    reason, actor, ts
)
SELECT id, session_id, student_id, old_status, new_status,
       reason, actor, ts
FROM attendance_audit;

ALTER TABLE attendance_audit RENAME TO attendance_audit_old;
ALTER TABLE attendance_audit_new RENAME TO attendance_audit;
