-- SQLite
ALTER TABLE classes  ADD COLUMN owner_email TEXT;

ALTER TABLE sessions ADD COLUMN has_lecturer INTEGER DEFAULT 0;
ALTER TABLE sessions ADD COLUMN lecturer_seen_at TEXT;

UPDATE classes
SET owner_email = 'nurfarhannis4@gmail.com'
WHERE id = 'CSC4400';

