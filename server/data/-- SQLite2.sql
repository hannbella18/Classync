-- SQLite
CREATE TABLE IF NOT EXISTS faculty (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  faculty_id TEXT UNIQUE NOT NULL,   -- e.g. FSKTM
  name       TEXT NOT NULL,          -- e.g. Fakulti Sains Komputer...
  address    TEXT                    -- optional
);

CREATE TABLE IF NOT EXISTS department (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  dept_id     TEXT UNIQUE NOT NULL,  -- e.g. COMP
  name        TEXT NOT NULL,         -- e.g. Jabatan Sains Komputer
  faculty_id  TEXT NOT NULL,         -- FK to faculty
  faculty_name TEXT,                 -- denormalised (optional)
  FOREIGN KEY (faculty_id) REFERENCES faculty(faculty_id)
);

ALTER TABLE classes ADD COLUMN dept_id   TEXT;
ALTER TABLE classes ADD COLUMN dept_name TEXT;

INSERT INTO faculty (faculty_id, name, address)
VALUES ('FSKTM', 'Fakulti Sains Komputer dan Teknologi Maklumat', 'Universiti Putra Malaysia, Serdang');

INSERT INTO department (dept_id, name, faculty_id, faculty_name)
VALUES 
('CSC', 'Jabatan Sains Komputer', 'FSKTM', 'Fakulti Sains Komputer dan Teknologi Maklumat'),
('SE', 'Jabatan Kejuruteraan Perisian', 'FSKTM', 'Fakulti Sains Komputer dan Teknologi Maklumat');

SELECT * FROM department WHERE id = 6;

BEGIN TRANSACTION;

CREATE TABLE classes_new (
    id             TEXT PRIMARY KEY,
    name           TEXT,
    platform_link  TEXT,
    created_at     TEXT NOT NULL,
    owner_email    TEXT,
    join_token     TEXT,
    owner_user_id  INTEGER,
    dept_id        INTEGER,
    FOREIGN KEY (owner_user_id) REFERENCES users(id),
    FOREIGN KEY (dept_id) REFERENCES department(id)
);

INSERT INTO classes_new (
    id, name, platform_link, created_at,
    owner_email, join_token, owner_user_id,
    dept_id
)
SELECT
    id, name, platform_link, created_at,
    owner_email, join_token, owner_user_id,
    dept_id
FROM classes;

DROP TABLE classes;
ALTER TABLE classes_new RENAME TO classes;

COMMIT;

SELECT * FROM department WHERE id = 1;

UPDATE classes
SET dept_id = 1
WHERE id = 'CSC4400';

SELECT id, name, dept_id FROM classes;
SELECT id, dept_id, name FROM department;






