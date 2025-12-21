-- SQLite
BEGIN TRANSACTION;

CREATE TABLE classes_new (
    id           TEXT PRIMARY KEY,
    name         TEXT,
    platform_link TEXT,
    created_at   TEXT NOT NULL,
    owner_email  TEXT,
    join_token   TEXT,
    owner_user_id INTEGER,
    FOREIGN KEY (owner_user_id) REFERENCES users(id)
);

INSERT INTO classes_new (id, name, platform_link, created_at, owner_email, join_token, owner_user_id)
SELECT id, name, platform_link, created_at, owner_email, join_token, owner_user_id
FROM classes;

DROP TABLE classes;
ALTER TABLE classes_new RENAME TO classes;

COMMIT;

BEGIN TRANSACTION;

CREATE TABLE sessions_new (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT,
    start_ts         TEXT NOT NULL,
    end_ts           TEXT,
    class_id         TEXT,
    platform_link    TEXT,
    week_no          INTEGER,
    term_id          TEXT,
    has_lecturer     INTEGER DEFAULT 0,
    lecturer_seen_at TEXT,
    FOREIGN KEY (class_id) REFERENCES classes(id),
    FOREIGN KEY (term_id)  REFERENCES terms(id)
);

INSERT INTO sessions_new (
    id, name, start_ts, end_ts,
    class_id, platform_link, week_no, term_id,
    has_lecturer, lecturer_seen_at
)
SELECT
    id, name, start_ts, end_ts,
    class_id, platform_link, week_no, term_id,
    has_lecturer, lecturer_seen_at
FROM sessions;

DROP TABLE sessions;
ALTER TABLE sessions_new RENAME TO sessions;

COMMIT;

BEGIN TRANSACTION;

CREATE TABLE events_new (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    student_id TEXT,
    type       TEXT,
    value      TEXT,
    ts         TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (student_id) REFERENCES students(id)
);

INSERT INTO events_new (id, session_id, student_id, type, value, ts)
SELECT id, session_id, student_id, type, value, ts
FROM events;

DROP TABLE events;
ALTER TABLE events_new RENAME TO events;

COMMIT;

BEGIN TRANSACTION;

CREATE TABLE enrollments_new (
  class_id     TEXT NOT NULL,
  student_id   TEXT NOT NULL,
  display_name TEXT,
  email        TEXT,
  PRIMARY KEY (class_id, student_id),
  FOREIGN KEY (class_id)   REFERENCES classes(id),
  FOREIGN KEY (student_id) REFERENCES students(id)
);

INSERT INTO enrollments_new (class_id, student_id, display_name, email)
SELECT class_id, student_id, display_name, email
FROM enrollments;

DROP TABLE enrollments;
ALTER TABLE enrollments_new RENAME TO enrollments;

COMMIT;

BEGIN TRANSACTION;

CREATE TABLE engagement_summary_new (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       INTEGER NOT NULL,
    class_id         TEXT    NOT NULL,
    student_id       TEXT    NOT NULL,
    drowsy_count     INTEGER NOT NULL DEFAULT 0,
    awake_count      INTEGER NOT NULL DEFAULT 0,
    tab_away_count   INTEGER NOT NULL DEFAULT 0,
    idle_seconds     INTEGER NOT NULL DEFAULT 0,
    engagement_score INTEGER NOT NULL DEFAULT 0,
    risk_level       TEXT    NOT NULL DEFAULT 'low',
    created_at       TEXT    NOT NULL,
    UNIQUE(session_id, student_id),
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (class_id)   REFERENCES classes(id),
    FOREIGN KEY (student_id) REFERENCES students(id)
);

INSERT INTO engagement_summary_new (
    id, session_id, class_id, student_id,
    drowsy_count, awake_count, tab_away_count,
    idle_seconds, engagement_score,
    risk_level, created_at
)
SELECT
    id, session_id, class_id, student_id,
    drowsy_count, awake_count, tab_away_count,
    idle_seconds, engagement_score,
    risk_level, created_at
FROM engagement_summary;

DROP TABLE engagement_summary;
ALTER TABLE engagement_summary_new RENAME TO engagement_summary;

COMMIT;

SELECT cs.*, c.name, c.owner_user_id
FROM course_schedule cs
JOIN classes c ON cs.class_id = c.id;

SELECT
    cs.id AS schedule_row_id,
    cs.class_id,
    cs.day_of_week,
    cs.time_start,
    cs.time_end,
    cs.location,
    cs.delivery_mode,
    c.name AS class_name,
    c.owner_user_id
FROM course_schedule cs
LEFT JOIN classes c ON cs.class_id = c.id;

UPDATE course_schedule
SET class_id = 'CSC4400';





