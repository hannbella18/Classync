import sqlite3
import os

# Use the same path as your Flask connect() function:
# .../server/data/app.db
db_path = os.path.join(os.path.dirname(__file__), "data", "app.db")
print("Using DB:", db_path)

conn = sqlite3.connect(db_path)
cur = conn.cursor()

rows = cur.execute(
    "SELECT id, start_ts, end_ts FROM sessions ORDER BY id DESC LIMIT 5"
).fetchall()

for r in rows:
    print(r)

conn.close()
