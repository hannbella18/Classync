# server/reset_db.py
import os, sqlite3
from datetime import datetime

# Path to server/data/app.db (adjust if your layout differs)
HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "data", "app.db")

KEEP_NAME = "Hannis"   # change if needed

def pick_one_hannis(cur):
    """
    If multiple 'Hannis' rows exist, pick one to keep.
    Preference: with embedding -> latest last_seen_ts -> lexicographically smallest id.
    Returns keep_id, delete_ids(list).
    """
    rows = cur.execute("""
        SELECT id, embedding, last_seen_ts
        FROM students
        WHERE name = ?
    """, (KEEP_NAME,)).fetchall()

    if not rows:
        return None, []

    def score(r):
        has_emb = 1 if r["embedding"] else 0
        try:
            ts = datetime.fromisoformat((r["last_seen_ts"] or "").replace("Z","+00:00"))
        except Exception:
            ts = datetime.min
        return (has_emb, ts, r["id"])

    rows_sorted = sorted(rows, key=score, reverse=True)
    keep_id = rows_sorted[0]["id"]
    delete_ids = [r["id"] for r in rows_sorted[1:]]
    return keep_id, delete_ids

def main():
    if not os.path.exists(DB_PATH):
        raise SystemExit(f"DB not found at {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Ensure tables exist (no-op if already there)
    # If your schema might be missing some tables in a fresh DB, wrap in try/excepts.

    # 1) Decide which Hannis to keep (or error if none)
    keep_id, dup_ids = pick_one_hannis(cur)
    if not keep_id:
        conn.close()
        raise SystemExit(f'No student named "{KEEP_NAME}" found in students table.')

    # 2) Begin cleanup
    cur.execute("BEGIN")

    # a) Delete duplicate Hannis rows (if any)
    if dup_ids:
        cur.executemany("DELETE FROM students WHERE id = ?", [(i,) for i in dup_ids])

    # b) Wipe activity/session tables
    cur.execute("DELETE FROM events")
    cur.execute("DELETE FROM attendance_audit")
    cur.execute("DELETE FROM attendance")
    cur.execute("DELETE FROM sessions")

    # c) Keep only the chosen Hannis row in students
    cur.execute("DELETE FROM students WHERE id <> ?", (keep_id,))

    # d) Reset AUTOINCREMENT counters
    cur.execute("""
        DELETE FROM sqlite_sequence
        WHERE name IN ('sessions','events','attendance','attendance_audit')
    """)

    conn.commit()

    # e) VACUUM to reclaim space
    try:
        cur.execute("VACUUM")
    except Exception:
        pass

    conn.close()
    print("✅ Reset complete")
    print(f"Kept student id: {keep_id}")
    if dup_ids:
        print(f"Removed duplicate Hannis ids: {', '.join(dup_ids)}")
    print(f"DB: {DB_PATH}")

if __name__ == "__main__":
    main()
