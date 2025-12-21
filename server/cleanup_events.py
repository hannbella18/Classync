import sqlite3, os, sys
DB = os.path.join(os.path.dirname(__file__), "data", "app.db")

def q(conn, sql, args=()):
    cur = conn.cursor()
    cur.execute(sql, args)
    conn.commit()
    return cur.rowcount

def count(conn, sql):
    cur = conn.cursor()
    return cur.execute(sql).fetchone()[0]

def main():
    conn = sqlite3.connect(DB)
    print("DB:", DB)

    before = count(conn, "SELECT COUNT(*) FROM events")
    print("events before:", before)

    # 1) drop NULL student_id
    n1 = q(conn, "DELETE FROM events WHERE student_id IS NULL")

    # 2) drop events for non-existent students
    n2 = q(conn, """
      DELETE FROM events
      WHERE student_id IS NOT NULL
        AND student_id NOT IN (SELECT id FROM students)
    """)

    # 3) clear attendance + sessions (optional full reset)
    n3a = q(conn, "DELETE FROM attendance")
    n3b = q(conn, "DELETE FROM sessions")

    # 4) optional: drop completely empty sessions (no remaining events)
    n4 = q(conn, """
      DELETE FROM sessions
      WHERE id NOT IN (SELECT DISTINCT session_id FROM events)
    """)

    con = sqlite3.connect("app.db")
    cur = con.cursor()
    cur.execute("DELETE FROM events")
    con.commit()
    con.close()
    print("✅ All events deleted successfully.")

    # 5) vacuum for a tidy file
    conn.execute("VACUUM")
    conn.close()

    print(f"deleted NULL student_id events: {n1}")
    print(f"deleted events for missing students: {n2}")
    print(f"deleted attendance rows: {n3a}")
    print(f"deleted sessions: {n3b}")
    print(f"deleted empty sessions: {n4}")

#if __name__ == "__main__":
    main()
