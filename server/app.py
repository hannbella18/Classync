# -------------------- Import --------------------
import os, sys, json, time, csv, tempfile, math, uuid, smtplib
import sqlite3  # Imported to keep existing code happy!
import psycopg2 # The new Supabase driver
import psycopg2.extras
from psycopg2 import Error as PgError, IntegrityError as PgIntegrityError

# --- MAGIC TRICK: Map Postgres Errors to SQLite Errors ---
# This fixes the "sqlite3 is not defined" errors
sqlite3.IntegrityError = PgIntegrityError
sqlite3.Error = PgError

from datetime import datetime, timezone, timedelta
from threading import Lock
from collections import defaultdict
from werkzeug.security import generate_password_hash, check_password_hash
from email.message import EmailMessage
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# Make ../ (project root that contains "vision/") importable first
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

# Now it's safe to import from vision/
from vision.auto_enrol import EmbedFactory
from vision.detector import Detector

import numpy as np
import cv2

from flask import (
    Flask, request, jsonify, render_template, redirect, url_for, session, flash, send_from_directory, make_response,
)
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from flask_login import LoginManager, login_required, current_user, UserMixin, login_user

# -------------------- Config --------------------
# ✅ CORRECT URI (Port 5432, No Brackets)
# Hybrid Link: Uses the AWS address (Network Safe) + Project ID Username (Tenant Safe)
# Golden Combination: Pooler Host + Project ID Username + Transaction Port
DB_URI = "postgresql://postgres.axddlamriytmdxuuurum:jWYgO0fNz1Rp6GAY@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres"
SECRET_KEY = "dev-secret-change-this"
SECURITY_PASSWORD_SALT = "classync-reset-salt-change-this"
EMAIL_ADDRESS = os.environ.get("CLASSYNC_EMAIL_ADDRESS", "your_email@gmail.com")
EMAIL_PASSWORD = os.environ.get("CLASSYNC_EMAIL_PASSWORD", "your-app-password")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Face / embedding thresholds
SIM_THRESHOLD   = 0.60
AMBIG_THR       = 0.45
MERGE_WITH_EXISTING = True
MERGE_ALPHA_NEW = 0.25
NEW_CONFIRM_FRAMES   = 5
NEW_CONFIRM_WINDOW_S = 6.0
RISK_LOW = 0.30
RISK_MED = 0.45

# -------------------- RESTORED GLOBALS (Fixes "SEEN is not defined" Errors) --------------------
SEEN = {}
PENDING_STATE = {}
_embed_lock = Lock()
_detector_lock = Lock()
_embed_factory = None
_detector = None

# -------------------- Flask app --------------------
app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = SECRET_KEY
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

socketio = SocketIO(app, cors_allowed_origins="*")
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# -------------------- Database Wrapper --------------------
class PgCursorWrapper:
    def __init__(self, cursor):
        self.cursor = cursor
        self._last_insert_id = None
    
    def execute(self, sql, params=()):
        # 🔑 THIS IS THE CRITICAL LINE
        # It fixes BOTH the ? syntax AND the rowid naming issue automatically
        sql = sql.replace("?", "%s").replace("rowid", "id") 
        
        if sql.strip().upper().startswith("INSERT") and "RETURNING" not in sql.upper():
            sql += " RETURNING id"
            try:
                self.cursor.execute(sql, params)
                row = self.cursor.fetchone()
                if row: self._last_insert_id = row[0]
            except Exception as e:
                raise e
        else:
            self.cursor.execute(sql, params)
            self._last_insert_id = None
        return self

    @property
    def lastrowid(self):
        return self._last_insert_id
    
    def fetchone(self):
        return self.cursor.fetchone()
    
    def fetchall(self):
        return self.cursor.fetchall()
        
    def __getattr__(self, name):
        return getattr(self.cursor, name)

class PgConnectionWrapper:
    def __init__(self, conn):
        self.conn = conn
        self.row_factory = None 
        
    def cursor(self):
        return PgCursorWrapper(self.conn.cursor())
        
    def commit(self):
        self.conn.commit()
        
    def close(self):
        self.conn.close()
        
    def execute(self, sql, params=()):
        return self.cursor().execute(sql, params)

def connect():
    try:
        raw_conn = psycopg2.connect(DB_URI, cursor_factory=psycopg2.extras.DictCursor)
        return PgConnectionWrapper(raw_conn)
    except Exception as e:
        print(f"❌ DB Connection Failed: {e}")
        return None

def exec_retry(cur, sql, params=(), retries=3, delay=0.2):
    return cur.execute(sql, params)

def table_has_column(conn, table, col):
    cur = conn.cursor()
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name=%s AND column_name=%s",
        (table, col)
    )
    return cur.fetchone() is not None

def init_db():
    print("Checking database...")
    conn = connect()
    if not conn: return
    cur = conn.cursor()

    # Define tables
    cur.execute("""CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, university TEXT, pw_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'lecturer', created_at TEXT NOT NULL, dept_id TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS students (id TEXT PRIMARY KEY, name TEXT, embedding TEXT, last_seen_ts TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS sessions (id SERIAL PRIMARY KEY, name TEXT, start_ts TEXT NOT NULL, end_ts TEXT, class_id TEXT, platform_link TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS events (id SERIAL PRIMARY KEY, session_id INTEGER, student_id TEXT, type TEXT, value TEXT, ts TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS classes (id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT, section TEXT, owner_user_id INTEGER, created_at TEXT NOT NULL, join_token TEXT, platform_link TEXT, location TEXT, dept_id INTEGER, owner_email TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS enrollments (id SERIAL PRIMARY KEY, class_id TEXT NOT NULL, student_id TEXT NOT NULL, display_name TEXT, email TEXT, UNIQUE(class_id, student_id))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS attendance (id SERIAL PRIMARY KEY, session_id INTEGER NOT NULL, student_id TEXT NOT NULL, status TEXT NOT NULL, first_seen_ts TEXT, last_seen_ts TEXT, UNIQUE(session_id, student_id))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS engagement_summary (id SERIAL PRIMARY KEY, session_id INTEGER NOT NULL, class_id TEXT NOT NULL, student_id TEXT NOT NULL, drowsy_count INTEGER NOT NULL DEFAULT 0, awake_count INTEGER NOT NULL DEFAULT 0, tab_away_count INTEGER NOT NULL DEFAULT 0, idle_seconds INTEGER NOT NULL DEFAULT 0, engagement_score INTEGER NOT NULL DEFAULT 0, risk_level TEXT NOT NULL DEFAULT 'low', created_at TEXT NOT NULL, UNIQUE(session_id, student_id))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS alerts (id SERIAL PRIMARY KEY, lecturer_id INTEGER, course TEXT, level TEXT, message TEXT, note TEXT, created_at TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS notifications (id SERIAL PRIMARY KEY, lecturer_id INTEGER, message TEXT, level TEXT, type TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS faculty (id SERIAL PRIMARY KEY, faculty_id TEXT UNIQUE NOT NULL, name TEXT NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS department (id SERIAL PRIMARY KEY, dept_id TEXT UNIQUE NOT NULL, name TEXT NOT NULL, faculty_id TEXT, faculty_name TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS course_schedule (id SERIAL PRIMARY KEY, class_id TEXT, delivery_mode TEXT, location TEXT, day_of_week INTEGER, time_start TEXT, time_end TEXT)""")

    conn.commit()
    conn.close()
    print("✅ Database connected & initialized!")

init_db()

class User(UserMixin):
    def __init__(self, id, name, email, role):
        self.id = id
        self.name = name
        self.email = email
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    # Manually fetch user from Supabase
    conn = connect()
    if not conn: return None
    cur = conn.cursor()
    
    # Run the SQL query
    row = cur.execute("SELECT id, name, email, role FROM users WHERE id=%s", (user_id,)).fetchone()
    conn.close()
    
    if row:
        # Return our new User object
        return User(id=row["id"], name=row["name"], email=row["email"], role=row["role"])
    return None
# -------------------- Helpers: time & IDs --------------------
def now_iso():
    return datetime.now(timezone.utc).isoformat()

def _now():
    return time.time()

def mint_next_student_id():
    conn = connect(); cur = conn.cursor()
    row = cur.execute(
        "SELECT id FROM students WHERE id LIKE 'S%%' "
        "ORDER BY CAST(SUBSTRING(id from 2) AS INTEGER) DESC LIMIT 1"
    ).fetchone()
    next_num = (int(row["id"][1:]) + 1) if row else 1
    sid = f"S{next_num:03d}"
    conn.close()
    return sid

# --- JSON-safe casters ---
def pfloat(x):
    try:
        return None if x is None else float(x)
    except Exception:
        return None

def pint(x):
    try:
        return None if x is None else int(x)
    except Exception:
        return None

def _safe_vec(ejson):
    if not ejson:
        return None
    try:
        v = np.asarray(json.loads(ejson), dtype=np.float32)
        if v.ndim != 1:
            return None
        return v
    except Exception:
        return None

def merge_or_replace_embedding(existing_json: str, new_vec: np.ndarray) -> str:
    """
    Returns a JSON string of the merged/replaced vector.
    """
    if not MERGE_WITH_EXISTING:
        return json.dumps(new_vec.tolist())

    old = _safe_vec(existing_json)
    if old is None or len(old) != len(new_vec):
        return json.dumps(new_vec.tolist())

    a = float(MERGE_ALPHA_NEW)
    merged = (1.0 - a) * old + a * new_vec
    norm = np.linalg.norm(merged)
    if norm > 1e-8:
        merged = merged / norm
    return json.dumps(merged.astype(np.float32).tolist())

def merge_embedding_into(conn, student_id: str, new_vec: np.ndarray) -> None:
    """
    Load the existing embedding for this student, merge with new_vec using
    merge_or_replace_embedding(), and write back to the database.
    """
    cur = conn.cursor()
    row = cur.execute(
        "SELECT embedding FROM students WHERE id=?",
        (student_id,),
    ).fetchone()

    existing_json = row["embedding"] if row else None
    merged_json = merge_or_replace_embedding(existing_json, new_vec)

    cur.execute(
        "UPDATE students SET embedding=? WHERE id=?",
        (merged_json, student_id),
    )
    conn.commit()

def verify_class_token(class_id: str, token: str) -> bool:
    """
    Check whether the provided token matches the join_token stored for the class.
    If no token is set for the class, it allows join by default.
    """
    if not class_id:
        return True

    conn = connect()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT join_token FROM classes WHERE id=?", (class_id,)
    ).fetchone()
    conn.close()

    if not row or not row["join_token"]:
        return True
    return token and (token == row["join_token"])

# Add the churn function
def compute_engagement_for_session(session_id):
    """
    Aggregate raw events + attendance into engagement_summary
    for each student in a given session.
    1 row per (session_id, student_id).
    """
    try:
        session_id = int(session_id)
    except Exception:
        return

    conn = connect(); cur = conn.cursor()

    # 1) Find the class_id for this session
    row = cur.execute(
        "SELECT class_id FROM sessions WHERE id=?",
        (session_id,),
    ).fetchone()
    class_id = row["class_id"] if row else None
    if not class_id:
        # fallback label so NOT NULL constraint is satisfied
        class_id = f"AUTO-{session_id}"

    # 1b) Find the lecturer (owner) for this class
    row_owner = cur.execute(
        "SELECT owner_user_id FROM classes WHERE id=?",
        (class_id,),
    ).fetchone()
    lecturer_id = row_owner["owner_user_id"] if row_owner else None

    # 2) Get all students with attendance for this session
    students = cur.execute(
        """
        SELECT student_id, status
        FROM attendance
        WHERE session_id=?
        """,
        (session_id,),
    ).fetchall()

    if not students:
        conn.close()
        return

    for st in students:
        sid = st["student_id"]
        status = (st["status"] or "").lower()

        # 3) Count events by type for this student+session
        ev_rows = cur.execute(
            """
            SELECT type, COUNT(*) AS cnt
            FROM events
            WHERE session_id=? AND student_id=?
            GROUP BY type
            """,
            (session_id, sid),
        ).fetchall()

        drowsy_count = 0
        awake_count = 0
        tab_away_count = 0

        # counts per type (drowsy / awake / tab_away)
        for ev in ev_rows:
            et = (ev["type"] or "").lower()
            if et == "drowsy":
                drowsy_count = ev["cnt"]
            elif et == "awake":
                awake_count = ev["cnt"]
            elif et == "tab_away":
                tab_away_count = ev["cnt"]

        # --- NEW: sum idle seconds from "idle" events ---
        idle_seconds = 0
        idle_rows = cur.execute(
            "SELECT value FROM events WHERE session_id=? AND student_id=? AND type='idle'",
            (session_id, sid),
        ).fetchall()

        for row2 in idle_rows:
            try:
                v = json.loads(row2["value"] or "{}")
            except Exception:
                continue

            dur = 0
            if isinstance(v, dict):
                # Case 1: duration_s stored at top level (future-proof)
                if "duration_s" in v:
                    try:
                        dur = int(float(v.get("duration_s", 0)))
                    except Exception:
                        dur = 0
                # Case 2: duration_s stored inside raw_value (current behaviour)
                elif isinstance(v.get("raw_value"), dict) and "duration_s" in v["raw_value"]:
                    try:
                        dur = int(float(v["raw_value"].get("duration_s", 0)))
                    except Exception:
                        dur = 0

            if dur > 0:
                idle_seconds += dur

        # 4) Simple engagement score (you can refine later)
        if status == "absent":
            score = 0
        else:
            score = 100
            score -= drowsy_count * 3
            score -= tab_away_count * 5   # already there
            # (optional) you can subtract a bit for idle if you want:
            # score -= idle_seconds // 30
            if score < 0:
                score = 0

        # 5) Map score -> risk_level
        if score >= 70:
            risk = "low"
        elif score >= 40:
            risk = "medium"
        else:
            risk = "high"

        # 6) Upsert into engagement_summary
        cur.execute(
            """
            INSERT INTO engagement_summary(
                session_id, class_id, student_id,
                drowsy_count, awake_count, tab_away_count,
                idle_seconds, engagement_score, risk_level, created_at
            )
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(session_id, student_id)
            DO UPDATE SET
              drowsy_count    = excluded.drowsy_count,
              awake_count     = excluded.awake_count,
              tab_away_count  = excluded.tab_away_count,
              idle_seconds    = excluded.idle_seconds,
              engagement_score= excluded.engagement_score,
              risk_level      = excluded.risk_level,
              created_at      = excluded.created_at
            """,
            (
                session_id,
                class_id,
                sid,
                drowsy_count,
                awake_count,
                tab_away_count,
                idle_seconds,            # idle_seconds (for now)
                score,
                risk,
                now_iso(),
            ),
        )

        # 7) DROWSY / ENGAGEMENT ALERT (type = drowsy_alert)
        if lecturer_id:
            notif_type = None
            notif_level = None

            # Rule: high risk -> red drowsy alert
            if risk == "high":
                notif_type = "drowsy_alert"
                notif_level = "red"
            # Rule: medium risk with many drowsy/tab-away -> yellow alert
            elif risk == "medium" and (drowsy_count >= 10 or tab_away_count >= 15):
                notif_type = "drowsy_alert"
                notif_level = "yellow"

            if notif_type:
                msg = (
                    f"Student {sid} is at {risk} engagement risk "
                    f"in {class_id} (session {session_id}): "
                    f"drowsy {drowsy_count}×, tab away {tab_away_count}×."
                )

                # avoid duplicates for same lecturer + student + session + type
                cur.execute(
                    """
                    DELETE FROM notifications
                    WHERE lecturer_id = ?
                    AND type = ?
                    AND message LIKE ?
                    """,
                    (lecturer_id, notif_type,
                    f"Student {sid} is at %session {session_id}%"),
                )

                cur.execute(
                    """
                    INSERT INTO notifications(lecturer_id, message, level, type)
                    VALUES (?,?,?,?)
                    """,
                    (lecturer_id, msg, notif_level, notif_type),
                )

        # 8) ATTENDANCE ALERT (type = attendance_alert)
        if lecturer_id:
            att_row = cur.execute(
                """
                SELECT
                SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) AS present_count,
                SUM(CASE WHEN a.status='absent'  THEN 1 ELSE 0 END) AS absent_count
                FROM attendance a
                JOIN sessions s ON a.session_id = s.id
                WHERE s.class_id = ? AND a.student_id = ?
                """,
                (class_id, sid),
            ).fetchone()

            present_count = att_row["present_count"] or 0
            absent_count  = att_row["absent_count"] or 0
            total_sessions = present_count + absent_count

            if total_sessions >= 3:  # only after a few sessions
                attendance_rate = present_count * 100 / total_sessions

                notif_type2 = None
                notif_level2 = None

                # Example rule: < 80% = yellow, < 60% = red
                if attendance_rate < 60:
                    notif_type2 = "attendance_alert"
                    notif_level2 = "red"
                elif attendance_rate < 80:
                    notif_type2 = "attendance_alert"
                    notif_level2 = "yellow"

                if notif_type2:
                    msg2 = (
                        f"Student {sid} has low attendance in {class_id}: "
                        f"{attendance_rate:.0f}% over {total_sessions} sessions."
                    )

                    cur.execute(
                        """
                        DELETE FROM notifications
                        WHERE lecturer_id = ?
                        AND type = ?
                        AND message LIKE ?
                        """,
                        (lecturer_id, notif_type2,
                        f"Student {sid} has low attendance in {class_id}%"),
                    )

                    cur.execute(
                        """
                        INSERT INTO notifications(lecturer_id, message, level, type)
                        VALUES (?,?,?,?)
                        """,
                        (lecturer_id, msg2, notif_level2, notif_type2),
                    )

        # === 9) CLASS-LEVEL ALERTS for the Alerts panel (table: alerts) ===
        # One row per class + alert type, based on recent sessions.
        if lecturer_id and class_id:
            try:
                # ---- 9a) Low engagement across sessions (Student low engagement)
                # Look at last 5 sessions of this class and count how many are < 50% avg engagement.
                eng_rows = cur.execute(
                    """
                    SELECT
                    es.session_id,
                    AVG(es.engagement_score) AS avg_eng
                    FROM engagement_summary es
                    WHERE es.class_id = ?
                    GROUP BY es.session_id
                    ORDER BY es.session_id DESC
                    LIMIT 5
                    """,
                    (class_id,),
                ).fetchall()

                low_sessions = 0
                for r in eng_rows:
                    avg_eng = r["avg_eng"] or 0.0
                    if avg_eng < 50.0:
                        low_sessions += 1

                # First remove any old "Student low engagement" alert for this class
                cur.execute(
                    """
                    DELETE FROM alerts
                    WHERE lecturer_id = ? AND course = ? AND message = 'Student low engagement'
                    """,
                    (lecturer_id, class_id),
                )

                if low_sessions > 0:
                    # 3 sessions below 50% -> High, otherwise Medium
                    if low_sessions >= 3:
                        level = "high"
                    else:
                        level = "medium"

                    note_text = (
                        f"{low_sessions} session below 50%"
                        if low_sessions == 1
                        else f"{low_sessions} sessions below 50%"
                    )

                    cur.execute(
                        """
                        INSERT INTO alerts(lecturer_id, course, level, message, note, created_at)
                        VALUES (?,?,?,?,?,?)
                        """,
                        (
                            lecturer_id,
                            class_id,
                            level,
                            "Student low engagement",
                            note_text,
                            now_iso(),
                        ),
                    )

                # ---- 9b) Attendance dropped alert (Attendance dropped)
                # Compare last session attendance vs overall average for this class.
                last_row = cur.execute(
                    """
                    SELECT id
                    FROM sessions
                    WHERE class_id = ?
                    ORDER BY start_ts DESC
                    LIMIT 1
                    """,
                    (class_id,),
                ).fetchone()

                # Always remove any old "Attendance dropped" alert for this class first
                cur.execute(
                    """
                    DELETE FROM alerts
                    WHERE lecturer_id = ? AND course = ? AND message = 'Attendance dropped'
                    """,
                    (lecturer_id, class_id),
                )

                if last_row:
                    last_session_id = last_row["id"]

                    last_att = cur.execute(
                        """
                        SELECT
                        SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) AS present_cnt,
                        COUNT(*) AS total_cnt
                        FROM attendance
                        WHERE session_id = ?
                        """,
                        (last_session_id,),
                    ).fetchone()

                    total_last = last_att["total_cnt"] or 0
                    present_last = last_att["present_cnt"] or 0

                    if total_last > 0:
                        last_rate = 100.0 * present_last / total_last

                        # overall attendance across all sessions in this class
                        all_att = cur.execute(
                            """
                            SELECT
                            SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) AS present_cnt,
                            COUNT(*) AS total_cnt
                            FROM attendance a
                            JOIN sessions s ON a.session_id = s.id
                            WHERE s.class_id = ?
                            """,
                            (class_id,),
                        ).fetchone()

                        total_all = all_att["total_cnt"] or 0
                        present_all = all_att["present_cnt"] or 0

                        if total_all > 0:
                            overall_rate = 100.0 * present_all / total_all
                        else:
                            overall_rate = last_rate

                        drop = overall_rate - last_rate

                        # Trigger an alert if last session < 80% and dropped ≥ 10 points
                        if last_rate < 80.0 and drop >= 10.0:
                            level2 = "medium" if last_rate >= 60.0 else "high"
                            note2 = f"Last session only {last_rate:.0f}%"

                            cur.execute(
                                """
                                INSERT INTO alerts(lecturer_id, course, level, message, note, created_at)
                                VALUES (?,?,?,?,?,?)
                                """,
                                (
                                    lecturer_id,
                                    class_id,
                                    level2,
                                    "Attendance dropped",
                                    note2,
                                    now_iso(),
                                ),
                            )

            except Exception as e:
                print("[alerts] failed to update alerts:", e, file=sys.stderr)

    conn.commit()
    conn.close()

# -------------------- Helpers: Email Verification --------------------
def get_serializer():
    return URLSafeTimedSerializer(app.config["SECRET_KEY"])


def send_reset_email(to_email: str, reset_url: str):
    """
    Sends a password reset email.
    For real deployment, set CLASSYNC_EMAIL_ADDRESS and CLASSYNC_EMAIL_PASSWORD
    as environment variables for your Gmail/app password.
    """
    print("[RESET] Sending password reset link to:", to_email)
    print("[RESET] Link:", reset_url)

    # ⚠️ If you don't want real email yet, comment everything below out.
    try:
        msg = EmailMessage()
        msg["Subject"] = "Classync – Reset your password"
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = to_email
        msg.set_content(
            f"Hi,\n\nYou requested a password reset for your Classync account.\n"
            f"Click the link below to set a new password (valid for 1 hour):\n\n"
            f"{reset_url}\n\n"
            "If you did not request this, you can ignore this email.\n"
        )

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)

        print("[RESET] Email sent successfully.")
    except Exception as e:
        print("[RESET] Failed to send email:", e)

# -------------------- Helpers: Embedding / Detector --------------------
def get_embedder() -> EmbedFactory:
    global _embed_factory
    with _embed_lock:
        if _embed_factory is None:
            _embed_factory = EmbedFactory()
        return _embed_factory

def get_detector() -> Detector:
    global _detector
    with _detector_lock:
        if _detector is None:
            _detector = Detector()
        return _detector

def cos_sim(a, b):
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-8
    return float(np.dot(a, b) / denom)

def find_largest_face_bbox(img_bgr):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)

    h, w = gray.shape[:2]
    if max(h, w) < 640:
        scale = 640.0 / max(h, w)
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)))

    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    tries = [
        dict(scaleFactor=1.05, minNeighbors=3, minSize=(40, 40)),
        dict(scaleFactor=1.08, minNeighbors=3, minSize=(50, 50)),
        dict(scaleFactor=1.1, minNeighbors=4, minSize=(60, 60)),
        dict(scaleFactor=1.2, minNeighbors=4, minSize=(70, 70)),
    ]
    faces = []
    for p in tries:
        fs = cascade.detectMultiScale(gray, **p)
        if len(fs):
            faces = fs
            break

    if not len(faces):
        h, w = gray.shape[:2]
        if max(h, w) > 900:
            small = cv2.resize(gray, (w // 2, h // 2))
            fs = cascade.detectMultiScale(
                small, scaleFactor=1.05, minNeighbors=3, minSize=(30, 30)
            )
            if len(fs):
                x, y, ww, hh = max(fs, key=lambda b: b[2] * b[3])
                return int(x * 2), int(y * 2), int((x + ww) * 2), int((y + hh) * 2)
        return None

    x, y, ww, hh = max(faces, key=lambda b: b[2] * b[3])
    return int(x), int(y), int(x + ww), int(y + hh)

# -------------------- API: Health  --------------------
@app.get("/api/health")
def api_health():
    """
    Simple health-check endpoint so frontend JS can detect the API base.
    """
    return jsonify({"ok": True, "status": "alive", "ts": now_iso()}), 200

# -------------------- Auth & Pages (unchanged) --------------------
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))  

# ===================== MAIN FUNCTION =====================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        print(f"--> LOGIN ATTEMPT: {email}") # Debug Print

        conn = connect()
        if not conn:
            return render_template("login.html", error="Database connection failed")
            
        cur = conn.cursor()
        row = cur.execute(
            """
            SELECT id, name, email, pw_hash,
                   COALESCE(role, 'lecturer') AS role
            FROM users
            WHERE lower(email)=?
            """,
            (email,),
        ).fetchone()
        conn.close()

        if row:
            print(f"--> USER FOUND: {row['email']} (Role: {row['role']})") # Debug Print
            
            if check_password_hash(row["pw_hash"], password):
                print("--> PASSWORD MATCH! Logging in...") # Debug Print
                
                # 1. Manual Session (Keeps your existing code happy)
                session["user_id"] = row["id"]
                session["role"] = row["role"]
                
                # 2. Flask-Login Session (Keeps the new User class happy)
                # We create a temporary User object just to log them in
                user_obj = User(
                    id=row["id"], 
                    name=row["name"], 
                    email=row["email"], 
                    role=row["role"]
                )
                login_user(user_obj) # <--- This is the magic key 🔑

                # 3. Redirect
                if row["role"] == "admin":
                    return redirect(url_for("admin_dashboard"))
                else:
                    return redirect(url_for("dashboard"))
            else:
                print("--> PASSWORD INCORRECT") # Debug Print
        else:
            print("--> USER NOT FOUND") # Debug Print

        return render_template("login.html", error="Invalid email or password")

    return render_template("login.html")

# --- TEMPORARY FIX ROUTE (UPDATED) ---
@app.route("/fix-my-db")
def fix_my_db():
    conn = connect()
    cur = conn.cursor()
    
    # 1. Fix Admin (Password: admin123)
    admin_hash = generate_password_hash("admin123")
    cur.execute("""
        UPDATE users 
        SET pw_hash = ?, role = 'admin' 
        WHERE email = 'admin@upm.edu.my'
    """, (admin_hash,))
    
    # 2. Fix Lecturer (Password: Hannis@18)
    # I am using the email exactly as seen in your screenshot
    lecturer_hash = generate_password_hash("Hannis@18")
    cur.execute("""
        UPDATE users 
        SET pw_hash = ?, role = 'lecturer'
        WHERE email = 'nurfarhannis4@gmail.com'
    """, (lecturer_hash,))
    
    conn.commit()
    conn.close()
    return "✅ SUCCESS: Admin pass is 'admin123'. Lecturer pass is 'Hannis@18'. Go Login!"

@app.route("/signup", methods=["GET", "POST"])
def signup():
    conn = connect(); cur = conn.cursor()
    error = None
    success = False

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        university = "UPM"  # default because your DB requires it

        if not (name and email and password):
            error = "Please fill in all required fields."
        else:
            try:
                pw_hash = generate_password_hash(password)
                cur.execute(
                    """
                    INSERT INTO users(name, email, university, pw_hash, created_at, role)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (name, email, university, pw_hash, now_iso(), "lecturer")
                )
                conn.commit()
                success = True
            except sqlite3.IntegrityError:
                error = "Email already registered."

    conn.close()
    return render_template("signup.html", error=error, success=success)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()

        if not email:
            error = "Please enter your email."
            return render_template("forgot_password.html", error=error)

        conn = connect(); cur = conn.cursor()
        row = cur.execute(
            "SELECT id, email FROM users WHERE lower(email)=?",
            (email,),
        ).fetchone()
        conn.close()

        # We don't reveal whether email exists or not (security)
        if row:
            s = get_serializer()
            token = s.dumps(email, salt=SECURITY_PASSWORD_SALT)
            reset_url = url_for("reset_password", token=token, _external=True)
            send_reset_email(email, reset_url)

        msg = "If that email exists in our system, a reset link has been sent."
        return render_template("forgot_password.html", message=msg)

    # GET
    return render_template("forgot_password.html")

@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    s = get_serializer()
    try:
        email = s.loads(
            token,
            salt=SECURITY_PASSWORD_SALT,
            max_age=3600,  # 1 hour
        )
    except SignatureExpired:
        flash("The reset link has expired. Please request a new one.", "error")
        return redirect(url_for("forgot_password"))
    except BadSignature:
        flash("Invalid reset link.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""

        if not password or not confirm:
            error = "Please fill in both password fields."
            return render_template("reset_password.html", error=error)

        if password != confirm:
            error = "Passwords do not match."
            return render_template("reset_password.html", error=error)

        pw_hash = generate_password_hash(password)

        conn = connect(); cur = conn.cursor()
        cur.execute(
            "UPDATE users SET pw_hash=? WHERE lower(email)=?",
            (pw_hash, email.lower()),
        )
        conn.commit()
        conn.close()

        flash("Password updated. You can now log in.", "success")
        return redirect(url_for("login"))

    # GET
    return render_template("reset_password.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ===================== ADMIN – DASHBOARD =====================
@app.route("/admin")
def admin_dashboard():
    if "user_id" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))

    # For now, you can reuse the same dashboard or create a new template later
    return render_template("admin_dashboard.html")

# ===================== ADMIN – CLASSES =====================
@app.route("/admin/classes")
def admin_classes():
    # Only allow logged-in admin
    if "user_id" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))

    conn = connect()
    cur = conn.cursor()

    # 🔹 Load classes + lecturer + department
    rows = cur.execute(
        """
        SELECT
          c.id          AS class_id,
          c.name        AS class_name,
          c.section     AS section,
          c.platform_link,
          c.location    AS class_location,
          c.dept_id     AS dept_id,
          u.id          AS lecturer_id,
          u.name        AS lecturer_name,
          u.email       AS lecturer_email,
          d.name        AS dept_name
        FROM classes c
        LEFT JOIN users      u ON u.id = c.owner_user_id
        LEFT JOIN department d ON d.id = c.dept_id
        ORDER BY c.id
        """
    ).fetchall()

    classes = []

    for r in rows:
        # 🔹 One schedule row per class (if exists)
        sched = cur.execute(
            """
            SELECT
              delivery_mode,
              location,
              day_of_week,
              time_start,
              time_end
            FROM course_schedule
            WHERE class_id = ?
            ORDER BY id
            LIMIT 1
            """,
            (r["class_id"],),
        ).fetchone()

        if sched:
            raw_mode = sched["delivery_mode"] or "Google Meet"

            # Text shown in table
            if raw_mode == "Google Meet":
                mode = "Online"
            elif raw_mode == "Face to face":
                mode = "Face to face"
            else:
                mode = raw_mode or "Online"

            # Value to pre-select in the <select> when editing
            if raw_mode == "Face to face":
                ui_mode = "Physical"   # because your dropdown uses "Physical"
            else:
                ui_mode = "Online"

            day_of_week = sched["day_of_week"]
            time_start  = (sched["time_start"] or "")[:5] if sched["time_start"] else ""
            time_end    = (sched["time_end"]   or "")[:5] if sched["time_end"]   else ""
        else:
            mode        = "Online"
            ui_mode     = "Online"
            day_of_week = None
            time_start  = ""
            time_end    = ""

        # Location & link come from classes table
        location = r["class_location"] or ""
        link     = r["platform_link"] or ""

        # Lecturer display: "Name (email)" or "-" if missing
        if r["lecturer_name"]:
            lecturer_display = r["lecturer_name"]
            if r["lecturer_email"]:
                lecturer_display += f" ({r['lecturer_email']})"
        else:
            lecturer_display = "-"

        classes.append(
            {
                "course_code":  r["class_id"],
                "course_name":  r["class_name"],
                "group_name":   r["section"] or "",
                "lecturer":     lecturer_display,
                "lecturer_id":  r["lecturer_id"],
                "mode":         mode,        # shown in table
                "ui_mode":      ui_mode,     # used by <select> in Edit
                "location":     location,
                "link":         link,
                "dept_name":    r["dept_name"] or "",
                "dept_id":      r["dept_id"],
                "day_of_week":  day_of_week,
                "time_start":   time_start,
                "time_end":     time_end,
            }
        )

    # 🔹 Department + lecturer lists for the form dropdowns
    dept_rows = cur.execute(
        "SELECT id, name FROM department ORDER BY name"
    ).fetchall()

    lecturer_rows = cur.execute(
        "SELECT id, name, email FROM users WHERE role = 'lecturer' ORDER BY name"
    ).fetchall()

    conn.close()

    departments = [dict(d) for d in dept_rows]
    lecturers   = [dict(l) for l in lecturer_rows]

    return render_template(
        "admin_classes.html",
        classes=classes,
        departments=departments,
        lecturers=lecturers,
    )

@app.route("/admin/create-class", methods=["POST"])
def admin_create_class():
    # Must be admin
    if "user_id" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))

    user_id = session["user_id"]

    # ---- Read basic fields from form ----
    course_code = (request.form.get("course_code") or "").strip()
    course_name = (request.form.get("course_name") or "").strip()
    group_name  = (request.form.get("group_name")  or "").strip()

    # UI mode from dropdown: Online / Physical / Hybrid
    ui_mode = (request.form.get("mode") or "Online").strip()

    # Map UI mode -> DB delivery_mode
    m = ui_mode.lower()
    if m == "online":
        db_mode = "Google Meet"
    elif m in ("physical", "face to face"):
        db_mode = "Face to face"
    elif m == "hybrid":
        # choose one base mode for hybrid
        db_mode = "Google Meet"
    else:
        db_mode = "Google Meet"

    # Location / link from form
    online_link   = (request.form.get("platform_link") or "").strip()
    room_location = (request.form.get("location") or "").strip()

    # Lecturer dropdown; default to current admin if empty/invalid
    lecturer_raw = (request.form.get("lecturer_id") or "").strip()
    try:
        lecturer_id = int(lecturer_raw) if lecturer_raw else user_id
    except ValueError:
        lecturer_id = user_id

    # Department dropdown
    dept_raw = request.form.get("dept_id")
    dept_id = int(dept_raw) if dept_raw not in (None, "", "0") else None

    # Day + time
    day_raw    = (request.form.get("day_of_week") or "").strip()
    time_start = (request.form.get("time_start")  or "").strip()
    time_end   = (request.form.get("time_end")    or "").strip()

    day_of_week = int(day_raw) if day_raw.isdigit() else None

    # Edit flags from hidden inputs
    is_edit       = (request.form.get("is_edit") or "").lower() == "yes"
    edit_class_id = (request.form.get("edit_class_id") or "").strip()

    if not course_code or not course_name:
        flash("Please fill in both Course code and Course name.", "error")
        return redirect(url_for("admin_classes"))

    # For edit, we always use existing ID; for create, use typed code
    class_id = edit_class_id if is_edit and edit_class_id else course_code

    created_at = now_iso()
    platform_link = online_link or None
    location_text = room_location or None

    conn = connect()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # ---- Get lecturer email for owner_email ----
    row_user = cur.execute(
        "SELECT email FROM users WHERE id = ?",
        (lecturer_id,),
    ).fetchone()
    owner_email = row_user["email"] if row_user else None

    # ================== NEW: schedule conflict check ==================
    conflict = None
    # Only check when we have full schedule info
    if lecturer_id and day_of_week and time_start and time_end:
        conflict = cur.execute(
            """
            SELECT cs.class_id,
                   cs.day_of_week,
                   cs.time_start,
                   cs.time_end,
                   c.name AS class_name
            FROM course_schedule cs
            JOIN classes c ON c.id = cs.class_id
            WHERE c.owner_user_id = ?
              AND cs.day_of_week = ?
              AND cs.class_id != ?
              AND NOT (
                    ?::time <= cs.time_start::time
                OR  ?::time >= cs.time_end::time
              )
            LIMIT 1
            """,
            (
                lecturer_id,
                day_of_week,
                class_id,      # exclude the same class when editing
                time_end,      # new end
                time_start,    # new start
            ),
        ).fetchone()

    if conflict:
        # There is already another class overlapping this time
        msg = (
            f"Schedule conflict: lecturer already has "
            f"{conflict['class_name']} "
            f"({conflict['time_start']}–{conflict['time_end']}) "
            f"on this day."
        )
        conn.close()
        flash(msg, "error")
        return redirect(url_for("admin_classes"))
    # ================== END conflict check ============================

    try:
        if is_edit:
            # ---------- UPDATE existing class ----------
            cur.execute(
                """
                UPDATE classes
                SET name = ?,
                    section = ?,
                    platform_link = ?,
                    location = ?,
                    owner_email = ?,
                    owner_user_id = ?,
                    dept_id = ?
                WHERE id = ?
                """,
                (
                    course_name,
                    group_name,
                    platform_link,
                    location_text,
                    owner_email,
                    lecturer_id,
                    dept_id,
                    class_id,
                ),
            )
        else:
            # ---------- INSERT new class ----------
            cur.execute(
                """
                INSERT INTO classes (
                    id, name, section,
                    platform_link, location,
                    created_at, owner_email, owner_user_id, dept_id
                )
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    class_id,
                    course_name,
                    group_name,
                    platform_link,
                    location_text,
                    created_at,
                    owner_email,
                    lecturer_id,
                    dept_id,
                ),
            )

        # ---------- Upsert course_schedule ----------
        sched = cur.execute(
            "SELECT id FROM course_schedule WHERE class_id = ? LIMIT 1",
            (class_id,),
        ).fetchone()

        if sched:
            cur.execute(
                """
                UPDATE course_schedule
                SET delivery_mode = ?,
                    location      = ?,
                    day_of_week   = ?,
                    time_start    = ?,
                    time_end      = ?
                WHERE id = ?
                """,
                (
                    db_mode,
                    location_text,
                    day_of_week,
                    time_start or None,
                    time_end or None,
                    sched["id"],
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO course_schedule (
                    class_id, delivery_mode, location,
                    day_of_week, time_start, time_end
                )
                VALUES (?,?,?,?,?,?)
                """,
                (
                    class_id,
                    db_mode,
                    location_text,
                    day_of_week,
                    time_start or None,
                    time_end or None,
                ),
            )

        conn.commit()

    except sqlite3.IntegrityError:
        conn.rollback()
        flash("A class with this course code already exists.", "error")

    except sqlite3.OperationalError as e:
        conn.rollback()
        flash(f"Could not create/update class (DB schema mismatch): {e}", "error")

    finally:
        conn.close()

    return redirect(url_for("admin_classes"))

@app.route("/admin/classes/<class_id>/delete", methods=["POST"])
def admin_delete_class(class_id):
    if "user_id" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))

    conn = connect()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM course_schedule WHERE class_id = ?", (class_id,))
        cur.execute("DELETE FROM classes WHERE id = ?", (class_id,))
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": str(e)}), 500
        flash("Could not delete class.", "error")
        return redirect(url_for("admin_classes"))
    finally:
        conn.close()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True})
    return redirect(url_for("admin_classes"))

# ===================== ADMIN – USERS =====================
@app.route("/admin/manage-users")
def admin_manage_users():
    if "user_id" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))

    conn = connect()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute(
        """
        SELECT
          u.id,
          u.name,
          u.email,
          u.role,
          u.created_at,
          u.pw_hash,
          u.dept_id,
          d.name         AS department_name,
          d.faculty_name AS faculty_name
        FROM users u
        LEFT JOIN department d
          ON d.dept_id = u.dept_id
        ORDER BY u.id
        """
    ).fetchall()

    users = []
    for r in rows:
        created = r["created_at"] or ""
        if created:
            created = str(created)[:10]

        users.append(
            {
                "id": r["id"],
                "name": r["name"],
                "email": r["email"],
                "role": (r["role"] or "lecturer").capitalize(),
                "created_at": created,
                "status": "Active",
                "pw_hash": r["pw_hash"],
                "dept_id": r["dept_id"],
                "department_name": r["department_name"] or "-",
                "faculty_name": r["faculty_name"] or "-",
            }
        )

    dept_rows = cur.execute(
        "SELECT dept_id, name, faculty_name FROM department ORDER BY name"
    ).fetchall()

    departments = [
        {
            "dept_id": d["dept_id"],
            "name": d["name"],
            "faculty_name": d["faculty_name"],
        }
        for d in dept_rows
    ]

    conn.close()

    return render_template("admin_users.html", users=users, departments=departments)

@app.route("/admin/create-user", methods=["POST"])
def admin_create_user():
    # only admin
    if "user_id" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))

    name     = (request.form.get("name") or "").strip()
    email    = (request.form.get("email") or "").strip().lower()
    role_raw = (request.form.get("role") or "lecturer").strip().lower()
    password = request.form.get("password") or ""
    dept_id  = request.form.get("department_id") or None

    # hidden fields
    is_edit       = (request.form.get("is_edit") or "").lower() == "yes"
    edit_user_id  = (request.form.get("edit_user_id") or "").strip()

    conn = connect()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # normalise role text
    role = "admin" if role_raw == "admin" else "lecturer"

    # ========== EDIT EXISTING USER ==========
    if is_edit and edit_user_id:
        try:
            user_id = int(edit_user_id)
        except ValueError:
            conn.close()
            return redirect(url_for("admin_manage_users"))

        if not (name and email):
            conn.close()
            return redirect(url_for("admin_manage_users"))

        try:
            # if password filled, update it; else keep old hash
            if password:
                pw_hash = generate_password_hash(password)
                cur.execute(
                    """
                    UPDATE users
                    SET name = ?, email = ?, role = ?, dept_id = ?, pw_hash = ?
                    WHERE id = ?
                    """,
                    (name, email, role, dept_id, pw_hash, user_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE users
                    SET name = ?, email = ?, role = ?, dept_id = ?
                    WHERE id = ?
                    """,
                    (name, email, role, dept_id, user_id),
                )

            conn.commit()
        except sqlite3.Error:
            conn.rollback()
        finally:
            conn.close()

        return redirect(url_for("admin_manage_users"))

    # ========== CREATE NEW USER ==========
    # require password when creating
    if not (name and email and password):
        conn.close()
        return redirect(url_for("admin_manage_users"))

    university = "UPM"  # keep consistent with signup()
    pw_hash = generate_password_hash(password)

    try:
        cur.execute(
            """
            INSERT INTO users (name, email, university, pw_hash, created_at, role, dept_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (name, email, university, pw_hash, now_iso(), role, dept_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
    finally:
        conn.close()

    return redirect(url_for("admin_manage_users"))

@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
def admin_delete_user(user_id):
    if "user_id" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))

    # (optional) don't allow deleting yourself
    if user_id == session.get("user_id"):
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": "You cannot delete your own account."}), 400
        flash("You cannot delete your own admin account.", "error")
        return redirect(url_for("admin_manage_users"))

    conn = connect()
    cur = conn.cursor()

    try:
        cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": str(e)}), 500
        flash("Could not delete user.", "error")
        return redirect(url_for("admin_manage_users"))
    finally:
        conn.close()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True})
    return redirect(url_for("admin_manage_users"))

# ===================== ADMIN – DEPARTMENTS =====================
@app.route("/admin/manage-departments")
def admin_departments():
    """Admin page to view/add/edit departments."""
    if "user_id" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))

    conn = connect()
    cur = conn.cursor()

    # Load faculties for dropdown
    faculty_rows = cur.execute(
        """
        SELECT id, faculty_id, name
        FROM faculty
        ORDER BY name
        """
    ).fetchall()

    # Load departments with their faculty info
    dept_rows = cur.execute(
        """
        SELECT
          d.id,
          d.dept_id,
          d.name,
          d.faculty_id,
          COALESCE(d.faculty_name, f.name) AS faculty_name
        FROM department d
        LEFT JOIN faculty f
          ON d.faculty_id = f.faculty_id
        ORDER BY d.id ASC
        """
    ).fetchall()

    conn.close()

    faculties   = [dict(f) for f in faculty_rows]
    departments = [dict(d) for d in dept_rows]

    return render_template(
        "admin_departments.html",
        faculties=faculties,
        departments=departments,
    )


@app.route("/admin/create-department", methods=["POST"])
def admin_create_department():
    """Create or update a department from the admin form."""
    if "user_id" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))

    # Fields from form
    dept_id    = (request.form.get("dept_id") or "").strip()
    name       = (request.form.get("name") or "").strip()
    faculty_id = (request.form.get("faculty_id") or "").strip()

    # Hidden flags for edit mode
    is_edit = (request.form.get("is_edit") or "").lower() == "yes"
    edit_id = (request.form.get("edit_department_id") or "").strip()

    if not dept_id or not name or not faculty_id:
        flash("Department code, name and faculty are required.", "error")
        return redirect(url_for("admin_departments"))

    conn = connect()
    cur = conn.cursor()

    try:
        # Resolve faculty_name from faculty table (if available)
        row = cur.execute(
            "SELECT name FROM faculty WHERE faculty_id = ?",
            (faculty_id,),
        ).fetchone()
        faculty_name = row["name"] if row else None

        if is_edit and edit_id:
            # Update existing department
            cur.execute(
                """
                UPDATE department
                SET dept_id = ?, name = ?, faculty_id = ?, faculty_name = ?
                WHERE id = ?
                """,
                (dept_id, name, faculty_id, faculty_name, edit_id),
            )
        else:
            # Insert new department
            cur.execute(
                """
                INSERT INTO department (dept_id, name, faculty_id, faculty_name)
                VALUES (?, ?, ?, ?)
                """,
                (dept_id, name, faculty_id, faculty_name),
            )

        conn.commit()
        flash("Department saved successfully.", "success")
    except sqlite3.IntegrityError as e:
        conn.rollback()
        # Likely UNIQUE constraint on dept_id
        flash(f"Could not save department (maybe code already used?): {e}", "error")
    except sqlite3.Error as e:
        conn.rollback()
        flash(f"Database error while saving department: {e}", "error")
    finally:
        conn.close()

    return redirect(url_for("admin_departments"))

@app.route("/admin/departments/<int:dept_pk>/delete", methods=["POST"])
def admin_delete_department(dept_pk):
    """Delete a department (if not used by any class)."""
    if "user_id" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))

    conn = connect()
    cur = conn.cursor()

    try:
        # Check if any class still uses this department
        row = cur.execute(
            "SELECT COUNT(*) AS cnt FROM classes WHERE dept_id = ?",
            (dept_pk,),
        ).fetchone()
        in_use = row["cnt"] if row else 0

        if in_use:
            msg = "Cannot delete department because some classes are linked to it."
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": False, "error": msg}), 400
            flash(msg, "error")
            return redirect(url_for("admin_departments"))

        cur.execute("DELETE FROM department WHERE id = ?", (dept_pk,))
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": str(e)}), 500
        flash("Could not delete department.", "error")
        return redirect(url_for("admin_departments"))
    finally:
        conn.close()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True})
    return redirect(url_for("admin_departments"))

# ===================== ADMIN – FACULTIES =====================
@app.route("/admin/faculties")
def admin_faculties():
    """Admin page to view/add/edit faculties."""
    if "user_id" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))

    conn = connect()
    cur = conn.cursor()

    # Load all faculties
    fac_rows = cur.execute(
        """
        SELECT id, faculty_id, name
        FROM faculty
        ORDER BY id ASC
        """
    ).fetchall()

    conn.close()

    faculties = [dict(f) for f in fac_rows]

    return render_template(
        "admin_faculties.html",
        faculties=faculties,
    )

@app.route("/admin/create-faculty", methods=["POST"])
def admin_create_faculty():
    """Create or update a faculty from the admin form."""
    if "user_id" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))

    faculty_code = (request.form.get("faculty_id") or "").strip()
    name         = (request.form.get("name") or "").strip()

    is_edit   = (request.form.get("is_edit") or "").lower() == "yes"
    edit_id   = (request.form.get("edit_faculty_id") or "").strip()

    if not faculty_code or not name:
        flash("Faculty code and name are required.", "error")
        return redirect(url_for("admin_faculties"))

    conn = connect()
    cur = conn.cursor()

    try:
        if is_edit and edit_id:
            # Update existing faculty
            cur.execute(
                """
                UPDATE faculty
                SET faculty_id = ?, name = ?
                WHERE id = ?
                """,
                (faculty_code, name, edit_id),
            )
        else:
            # Insert new faculty
            cur.execute(
                """
                INSERT INTO faculty (faculty_id, name)
                VALUES (?, ?)
                """,
                (faculty_code, name),
            )

        conn.commit()
        flash("Faculty saved successfully.", "success")

    except sqlite3.IntegrityError as e:
        conn.rollback()
        # Probably UNIQUE constraint on faculty_id
        flash(f"Could not save faculty (maybe code already used?): {e}", "error")
    except sqlite3.Error as e:
        conn.rollback()
        flash(f"Database error while saving faculty: {e}", "error")
    finally:
        conn.close()

    return redirect(url_for("admin_faculties"))

@app.route("/admin/faculties/<int:faculty_pk>/delete", methods=["POST"])
def admin_delete_faculty(faculty_pk):
    """Delete a faculty, only if no departments use it."""
    if "user_id" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))

    conn = connect()
    cur = conn.cursor()

    try:
        # First get faculty_id code for this PK
        row_fac = cur.execute(
            "SELECT faculty_id FROM faculty WHERE id = ?",
            (faculty_pk,),
        ).fetchone()

        if not row_fac:
            msg = "Faculty not found."
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": False, "error": msg}), 404
            flash(msg, "error")
            return redirect(url_for("admin_faculties"))

        faculty_code = row_fac["faculty_id"]

        # Check whether any department still uses this faculty_id
        row = cur.execute(
            "SELECT COUNT(*) AS cnt FROM department WHERE faculty_id = ?",
            (faculty_code,),
        ).fetchone()
        in_use = row["cnt"] if row else 0

        if in_use:
            msg = "Cannot delete faculty because some departments are linked to it."
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": False, "error": msg}), 400
            flash(msg, "error")
            return redirect(url_for("admin_faculties"))

        # Safe to delete
        cur.execute("DELETE FROM faculty WHERE id = ?", (faculty_pk,))
        conn.commit()

    except sqlite3.Error as e:
        conn.rollback()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": str(e)}), 500
        flash("Could not delete faculty.", "error")
        return redirect(url_for("admin_faculties"))
    finally:
        conn.close()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True})

    return redirect(url_for("admin_faculties"))

# ===================== LECTURER – DASHBOARD SECTION =====================
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))
    user_id = session["user_id"]

    # --- ADD THESE DEFAULTS TO PREVENT CRASH ---
    overview = {"avg_engagement": 0, "camera_on": 0, "absent_rate": 0, "at_risk": 0}
    trend = {
        "avg": {"dir": "flat", "delta": 0, "text": "No data"},
        "camera": {"dir": "flat", "delta": 0, "text": "No data"},
        "absent": {"dir": "flat", "delta": 0, "text": "No data"},
        "risk": {"dir": "flat", "delta": 0, "text": "No data"}
    }

    conn = connect(); cur = conn.cursor()

    # --- Recent classes for the table ---
    classes = cur.execute(
        """
        SELECT id, name, platform_link, created_at
        FROM classes
        WHERE owner_user_id = ?
        ORDER BY created_at DESC
        """,
        (user_id,),
    ).fetchall()

    # --- Alerts for the Alerts card ---
    alerts = cur.execute(
        """
        SELECT level, course, message, note, created_at
        FROM alerts
        WHERE lecturer_id = ?
        ORDER BY created_at DESC
        LIMIT 5
        """,
        (user_id,),
    ).fetchall()

    # --- Notifications for the bell panel ---
    notifications = cur.execute(
        """
        SELECT message, level, created_at
        FROM notifications
        WHERE lecturer_id = ?
        ORDER BY created_at DESC
        LIMIT 10
        """,
        (user_id,),
    ).fetchall()

    # ----- Overall attendance summary (for donut) -----
    rows = cur.execute(
        """
        SELECT status, COUNT(*) AS cnt
        FROM attendance
        GROUP BY status
        """
    ).fetchall()

    attendance_data = {"present": 0, "absent": 0, "late": 0}
    total = sum(r["cnt"] for r in rows)

    if total > 0:
        for r in rows:
            key = (r["status"] or "").lower()
            if key in attendance_data:
                attendance_data[key] = round(r["cnt"] * 100.0 / total)

    # --- Average engagement by course (use engagement_summary) ---
    rows_ce = cur.execute(
        """
        SELECT
          es.class_id,
          c.name AS class_name,
          AVG(es.engagement_score) AS avg_score
        FROM engagement_summary es
        JOIN classes c ON es.class_id = c.id
        WHERE c.owner_user_id = ?
        GROUP BY es.class_id, c.name, c.id
        ORDER BY c.id
        """,
        (user_id,),
    ).fetchall()

    course_engagement = []
    for r in rows_ce:
        percent = int(round(r["avg_score"] or 0))
        course_engagement.append(
            {
                "id": r["class_id"],
                "name": r["class_name"],
                "percent": percent,
            }
        )
    
        # ---- Engagement Overview KPIs + week-to-week trend ----
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)
        this_start = (now - timedelta(days=7)).isoformat()
        last_start_dt = now - timedelta(days=14)
        last_start = last_start_dt.isoformat()
        last_end = this_start

        def _delta(curr, prev):
            """Return (diff, direction: 'up'/'down'/'flat')."""
            curr = float(curr or 0.0)
            prev = float(prev or 0.0)
            if prev == 0:
                return 0.0, "flat"
            diff = curr - prev
            if diff > 0:
                return diff, "up"
            if diff < 0:
                return diff, "down"
            return 0.0, "flat"

        # 1) Avg engagement (this week vs last week)
        row_this = cur.execute(
            """
            SELECT AVG(es.engagement_score) AS avg_eng
            FROM engagement_summary es
            JOIN classes c ON es.class_id = c.id
            WHERE c.owner_user_id = ?
            AND es.created_at >= ?
            """,
            (user_id, this_start),
        ).fetchone()
        row_last = cur.execute(
            """
            SELECT AVG(es.engagement_score) AS avg_eng
            FROM engagement_summary es
            JOIN classes c ON es.class_id = c.id
            WHERE c.owner_user_id = ?
            AND es.created_at >= ? AND es.created_at < ?
            """,
            (user_id, last_start, this_start),
        ).fetchone()

        avg_this = float(row_this["avg_eng"] or 0.0)
        avg_last = float(row_last["avg_eng"] or 0.0)
        d_avg, dir_avg = _delta(avg_this, avg_last)

        # 2) Camera on (% with at least one awake/drowsy event)
        row_cam_this = cur.execute(
            """
            SELECT
            SUM(CASE WHEN (es.awake_count + es.drowsy_count) > 0 THEN 1 ELSE 0 END) AS with_face,
            COUNT(*) AS total_rows
            FROM engagement_summary es
            JOIN classes c ON es.class_id = c.id
            WHERE c.owner_user_id = ?
            AND es.created_at >= ?
            """,
            (user_id, this_start),
        ).fetchone()
        row_cam_last = cur.execute(
            """
            SELECT
            SUM(CASE WHEN (es.awake_count + es.drowsy_count) > 0 THEN 1 ELSE 0 END) AS with_face,
            COUNT(*) AS total_rows
            FROM engagement_summary es
            JOIN classes c ON es.class_id = c.id
            WHERE c.owner_user_id = ?
            AND es.created_at >= ? AND es.created_at < ?
            """,
            (user_id, last_start, this_start),
        ).fetchone()

        cam_this = (
            100.0 * row_cam_this["with_face"] / row_cam_this["total_rows"]
            if row_cam_this["total_rows"] else 0.0
        )
        cam_last = (
            100.0 * row_cam_last["with_face"] / row_cam_last["total_rows"]
            if row_cam_last["total_rows"] else 0.0
        )
        d_cam, dir_cam = _delta(cam_this, cam_last)

        # 3) Absent rate (attendance, by sessions in last 7 days)
        row_abs_this = cur.execute(
            """
            SELECT
            SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) AS absent_cnt,
            COUNT(*) AS total_cnt
            FROM attendance a
            JOIN sessions s ON a.session_id = s.id
            JOIN classes  c ON s.class_id = c.id
            WHERE c.owner_user_id = ?
            AND s.start_ts >= ?
            """,
            (user_id, this_start),
        ).fetchone()
        row_abs_last = cur.execute(
            """
            SELECT
            SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) AS absent_cnt,
            COUNT(*) AS total_cnt
            FROM attendance a
            JOIN sessions s ON a.session_id = s.id
            JOIN classes  c ON s.class_id = c.id
            WHERE c.owner_user_id = ?
            AND s.start_ts >= ? AND s.start_ts < ?
            """,
            (user_id, last_start, this_start),
        ).fetchone()

        abs_this = (
            100.0 * row_abs_this["absent_cnt"] / row_abs_this["total_cnt"]
            if row_abs_this["total_cnt"] else 0.0
        )
        abs_last = (
            100.0 * row_abs_last["absent_cnt"] / row_abs_last["total_cnt"]
            if row_abs_last["total_cnt"] else 0.0
        )
        d_abs, dir_abs = _delta(abs_this, abs_last)

        # 4) At-risk students (risk_level='high')
        row_risk_this = cur.execute(
            """
            SELECT COUNT(DISTINCT es.student_id) AS cnt
            FROM engagement_summary es
            JOIN classes c ON es.class_id = c.id
            WHERE c.owner_user_id = ?
            AND es.risk_level = 'high'
            AND es.created_at >= ?
            """,
            (user_id, this_start),
        ).fetchone()
        row_risk_last = cur.execute(
            """
            SELECT COUNT(DISTINCT es.student_id) AS cnt
            FROM engagement_summary es
            JOIN classes c ON es.class_id = c.id
            WHERE c.owner_user_id = ?
            AND es.risk_level = 'high'
            AND es.created_at >= ? AND es.created_at < ?
            """,
            (user_id, last_start, this_start),
        ).fetchone()

        risk_this = float(row_risk_this["cnt"] or 0.0)
        risk_last = float(row_risk_last["cnt"] or 0.0)
        d_risk, dir_risk = _delta(risk_this, risk_last)

        # Main values shown in big text (this week)
        overview = {
            "avg_engagement": int(round(avg_this)),
            "camera_on": int(round(cam_this)),
            "absent_rate": int(round(abs_this)),
            "at_risk": int(round(risk_this)),
        }

        # Trend info just for the green/red text + arrow
        trend = {
            "avg": {
                "dir": dir_avg,
                "delta": round(d_avg, 1),
                "text": (
                    f"{d_avg:+.1f}% vs last week"
                    if dir_avg != "flat" else "No change vs last week"
                ),
            },
            "camera": {
                "dir": dir_cam,
                "delta": round(d_cam, 1),
                "text": (
                    f"{d_cam:+.1f}% vs last week"
                    if dir_cam != "flat" else "No change vs last week"
                ),
            },
            "absent": {
                "dir": dir_abs,
                "delta": round(d_abs, 1),
                "text": (
                    f"{d_abs:+.1f}% vs last week"
                    if dir_abs != "flat" else "No change vs last week"
                ),
            },
            "risk": {
                "dir": dir_risk,
                "delta": round(d_risk, 1),
                "text": (
                    f"{d_risk:+.1f} vs last week"
                    if dir_risk != "flat" else "No change vs last week"
                ),
            },
        }
    
    # ----- Weekly schedule for calendar (from course_schedule) -----
    rows_sched = cur.execute(
        """
        SELECT
          cs.day_of_week,
          cs.time_start,
          cs.time_end,
          cs.location,
          cs.delivery_mode,
          cs.class_id,
          c.name AS class_name
        FROM course_schedule cs
        JOIN classes c ON cs.class_id = c.id
        WHERE c.owner_user_id = ?
        ORDER BY cs.day_of_week, cs.time_start
        """,
        (user_id,),
    ).fetchall()

    schedule_by_day = {}
    for r in rows_sched:
        day_key = str(r["day_of_week"])        # "1".."7"
        t_start = (r["time_start"] or "")[:5]  # "HH:MM"
        t_end   = (r["time_end"] or "")[:5]

        schedule_by_day.setdefault(day_key, []).append(
            {
                "class_id": r["class_id"],
                "class_name": r["class_name"] or r["class_id"],
                "time_start": t_start,
                "time_end": t_end,
                "location": r["location"] or "",
                "delivery_mode": r["delivery_mode"] or "",
            }
        )


    conn.close()
    # Pass both classes + alerts to the template
    return render_template(
        "dashboard_main.html",
        classes=classes,
        alerts=alerts,
        notifications=notifications,
        attendance_data=attendance_data,
        course_engagement=course_engagement,
        overview=overview,
        trend=trend,
        schedule_by_day=schedule_by_day
    )

# ===================== LECTURER – ANALYSIS SECTION =====================
@app.route("/lecturer/analysis")
def lecturer_analysis():
    return render_template("lecturer_analysis.html")


# ===================== LECTURER – SETTINGS SECTION =====================
@app.route("/lecturer/settings", methods=["GET", "POST"])
def lecturer_settings():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user_id = session["user_id"]

    conn = connect()
    cur = conn.cursor()

    # ---------- POST: Save department + name ----------
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        dept_id = request.form.get("dept_id")

        cur.execute("""
            UPDATE users
            SET name = ?, dept_id = ?
            WHERE id = ?
        """, (name, dept_id, user_id))

        conn.commit()
        conn.close()
        return redirect(url_for("lecturer_settings"))

    # ---------- GET: Load notifications ----------
    notifications = cur.execute("""
        SELECT type, message, level, created_at
        FROM notifications
        WHERE lecturer_id = ?
        ORDER BY created_at DESC
        LIMIT 10
    """, (user_id,)).fetchall()

    # ---------- GET: Load departments ----------
    departments = cur.execute("""
        SELECT dept_id, name, faculty_name
        FROM department
        ORDER BY faculty_name, name
    """).fetchall()

    current_dept = cur.execute("""
        SELECT dept_id FROM users WHERE id = ?
    """, (user_id,)).fetchone()

    current_dept_id = current_dept["dept_id"] if current_dept else None

    conn.close()

    return render_template(
        "lecturer_settings.html",
        notifications=notifications,
        departments=departments,
        current_dept_id=current_dept_id
    )

@app.route("/lecturer/change-password", methods=["POST"])
def lecturer_change_password():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user_id = session["user_id"]

    current_pw = request.form.get("current_password", "")
    new_pw = request.form.get("new_password", "")
    confirm_pw = request.form.get("confirm_password", "")

    # Basic validation
    if not current_pw or not new_pw or not confirm_pw:
        flash("Please fill in all password fields.", "error")
        return redirect(url_for("lecturer_settings"))

    if new_pw != confirm_pw:
        flash("New password and confirmation do not match.", "error")
        return redirect(url_for("lecturer_settings"))

    if len(new_pw) < 8:
        flash("New password must be at least 8 characters.", "error")
        return redirect(url_for("lecturer_settings"))

    conn = connect()
    cur = conn.cursor()

    row = cur.execute("SELECT pw_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        conn.close()
        flash("User not found.", "error")
        return redirect(url_for("lecturer_settings"))

    if not check_password_hash(row["pw_hash"], current_pw):
        conn.close()
        flash("Current password is incorrect.", "error")
        return redirect(url_for("lecturer_settings"))

    new_hash = generate_password_hash(new_pw)  # uses werkzeug default (secure)

    cur.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (new_hash, user_id))
    conn.commit()
    conn.close()

    flash("Password updated successfully.", "success")
    return redirect(url_for("lecturer_settings"))

@app.route("/api/dashboard/recent-sessions")
def api_dashboard_recent_sessions():
    # Must be logged in
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    user_id = session["user_id"]

    conn = connect(); cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT
          s.id          AS session_id,
          s.start_ts    AS start_ts,
          s.end_ts      AS end_ts,
          s.class_id    AS class_id,
          COALESCE(s.platform_link, c.platform_link) AS platform_link,
          c.name        AS class_name
        FROM sessions s
        JOIN classes c
          ON s.class_id = c.id
        WHERE c.owner_user_id = ?
        ORDER BY s.start_ts DESC
        LIMIT 3
        """,
        (user_id,),
    ).fetchall()
    conn.close()

    sessions = []
    for idx, r in enumerate(rows, start=1):
        sessions.append(
            {
                "index": idx,                         # 1., 2., 3.
                "session_id": r["session_id"],
                "class_id": r["class_id"],           # e.g. CSC4400
                "class_name": r["class_name"],       # e.g. Software Testing
                "meet_link": r["platform_link"],     # may be None
                "start_ts": r["start_ts"],
                "end_ts": r["end_ts"],
            }
        )

    return jsonify({"ok": True, "sessions": sessions})

@app.post("/api/notifications/clear")
def api_notifications_clear():
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    user_id = session["user_id"]

    conn = connect(); cur = conn.cursor()
    cur.execute("DELETE FROM notifications WHERE lecturer_id=?", (user_id,))
    conn.commit()
    conn.close()

    return jsonify({"ok": True})

# ===================== LECTURER - COURSE SECTION =====================
@app.route("/courses")
def courses():
    if "user_id" not in session:
        return redirect(url_for("login"))
    user_id = session["user_id"]

    conn = connect(); cur = conn.cursor()

    # ✅ Pull notifications for this lecturer
    notifications = cur.execute(
        """
        SELECT message, level, created_at
        FROM notifications
        WHERE lecturer_id = ?
        ORDER BY created_at DESC
        LIMIT 10
        """,
        (user_id,),
    ).fetchall()

    rows = cur.execute(
        """
        SELECT
            c.id,              -- class code e.g. CSC4300-1
            c.name,            -- class name
            c.dept_id,         -- FK to department.id
            d.name AS dept_name
        FROM classes c
        LEFT JOIN department d ON c.dept_id = d.id   -- 👈 important
        WHERE c.owner_user_id = ?
        ORDER BY c.id
        """,
        (user_id,),
    ).fetchall()

    conn.close()

    classes = [dict(r) for r in rows]

    return render_template("courses.html", 
                           classes=classes,
                           notifications=notifications)

# ===================== LECTURER - SUMMARY PAGE =====================
@app.route("/join/<class_id>")
def join_class_page(class_id):
    """
    Join page for students (no login).
    We only render HTML here. Camera + identify happen in join.js.
    """
    token = (request.args.get("token") or "").strip()

    conn = connect()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT id, name FROM classes WHERE id=?",
        (class_id,),
    ).fetchone()
    conn.close()

    if not row:
        return "Class not found.", 404

    return render_template(
        "join.html",
        class_id=row["id"],
        class_name=row["name"],
        token=token,
    )

@app.route("/summary")
def summary():
    class_id = request.args.get("class_id")
    # ✅ DEFINE user_id before using it
    user_id = session["user_id"]

    conn = connect()
    cur = conn.cursor()

    # ✅ Notifications for the bell panel
    notifications = cur.execute(
        """
        SELECT message, level, created_at
        FROM notifications
        WHERE lecturer_id = ?
        ORDER BY created_at DESC
        LIMIT 10
        """,
        (user_id,),
    ).fetchall()

    row = cur.execute("""
        SELECT id, name
        FROM classes
        WHERE id = ?
    """, (class_id,)).fetchone()

    conn.close()

    class_code = row["id"] if row else "Unknown Class"
    class_name = row["name"] if row else ""

    return render_template(
        "summary.html",
        class_code=class_code,
        class_name=class_name,
        notifications = notifications
    )

@app.route("/session/<int:session_id>")
def session_summary(session_id):
    conn = connect(); cur = conn.cursor()

    session_row = cur.execute(
        "SELECT id, name, start_ts, end_ts FROM sessions WHERE id=?", (session_id,)
    ).fetchone()

    events = cur.execute(
        "SELECT student_id, type, value, ts FROM events WHERE session_id=? "
        "ORDER BY ts ASC",
        (session_id,),
    ).fetchall()

    conn.close()
    return render_template("summary.html", session=session_row, events=events)

@app.route("/classync-extension")
def classync_extension_page():
    return render_template("student_extension.html")

# -------------------- Time Helpers --------------------
LOCAL_TZ = timezone(timedelta(hours=8))  # Malaysia time (UTC+8)


def format_session_label(row):
    """
    Convert session start_ts (stored in UTC) to local time for display.
    """
    raw = row["start_ts"]
    try:
        dt = datetime.fromisoformat(raw)           # parse DB value
        dt_local = dt.astimezone(LOCAL_TZ)         # convert to MY time
        pretty = dt_local.strftime("%Y-%m-%d %H:%M")
    except Exception:
        # fallback if anything weird in DB
        pretty = raw.replace("T", " ")[:16]

    return f"Session {row['id']} – {pretty}"

# -------------------- Classes & Attendance Helpers --------------------
def mark_attendance_if_needed(conn, session_id, student_id, ts_iso):
    cur = conn.cursor()
    r = cur.execute(
        "SELECT id, status, first_seen_ts, last_seen_ts "
        "FROM attendance WHERE session_id=? AND student_id=?",
        (session_id, student_id),
    ).fetchone()
    if not r:
        cur.execute(
            "INSERT INTO attendance(session_id, student_id, status, first_seen_ts, last_seen_ts) "
            "VALUES(?,?,?,?,?)",
            (session_id, student_id, "present", ts_iso, ts_iso),
        )
    else:
        cur.execute(
            "UPDATE attendance SET last_seen_ts=? WHERE id=?",
            (ts_iso, r["id"]),
        )

def get_open_session_id(conn):
    cur = conn.cursor()
    r = cur.execute(
        "SELECT id FROM sessions WHERE end_ts IS NULL ORDER BY start_ts DESC LIMIT 1"
    ).fetchone()
    return r["id"] if r else None

# ===================== LECTURER – ANALYSIS DROPDOWNS =====================

@app.get("/api/lecturer/courses")
def api_lecturer_courses():
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    user_id = session["user_id"]

    conn = connect(); cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id AS course_id, name AS course_name
        FROM classes
        WHERE owner_user_id = ?
        ORDER BY id
        """,
        (user_id,),
    ).fetchall()
    conn.close()

    return jsonify({"ok": True, "courses": [dict(r) for r in rows]})


@app.get("/api/lecturer/sessions")
def api_lecturer_sessions():
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    user_id = session["user_id"]
    course_id = (request.args.get("course_id") or "").strip()

    conn = connect(); cur = conn.cursor()

    # Only sessions for lecturer's classes; optionally filter by one course_id
    params = [user_id]
    where_course = ""
    if course_id:
        where_course = " AND s.class_id = ? "
        params.append(course_id)

    rows = cur.execute(
        f"""
        SELECT s.id, s.class_id, s.start_ts, s.end_ts
        FROM sessions s
        JOIN classes c ON c.id = s.class_id
        WHERE c.owner_user_id = ?
        {where_course}
        ORDER BY s.start_ts DESC
        LIMIT 80
        """,
        tuple(params),
    ).fetchall()

    conn.close()

    # Use your existing label formatter (already in app.py)
    sessions_out = []
    default_session_id = None
    for r in rows:
        label = format_session_label(r)
        is_open = r["end_ts"] is None
        if is_open:
            label += " (live)"

        sessions_out.append(
            {
                "id": r["id"],
                "class_id": r["class_id"],
                "label": label,
                "is_open": is_open,
                "start_ts": r["start_ts"],
                "end_ts": r["end_ts"],
            }
        )

        if default_session_id is None:
            default_session_id = r["id"]
        if is_open:
            default_session_id = r["id"]

    return jsonify({"ok": True, "sessions": sessions_out, "default_session_id": default_session_id})

@app.get("/api/lecturer/analytics/kpis")
def api_lecturer_kpis():
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    user_id = session["user_id"]
    session_id = request.args.get("session_id", type=int)

    if not session_id:
        return jsonify({"ok": False, "error": "missing_session_id"}), 400

    conn = connect()
    cur = conn.cursor()

    # Ensure this session belongs to this lecturer
    owns = cur.execute("""
        SELECT 1
        FROM sessions s
        JOIN classes c ON c.id = s.class_id
        WHERE s.id = ? AND c.owner_user_id = ?
    """, (session_id, user_id)).fetchone()

    if not owns:
        conn.close()
        return jsonify({"ok": False, "error": "forbidden"}), 403

    r = cur.execute("""
        SELECT
          AVG(engagement_score) AS avg_eng,
          COUNT(DISTINCT student_id) AS active_students,
          SUM(drowsy_count) AS drowsy_total,
          SUM(tab_away_count) AS tab_total
        FROM engagement_summary
        WHERE session_id = ?
    """, (session_id,)).fetchone()

    conn.close()

    return jsonify({
        "ok": True,
        "kpis": {
            "avg_engagement": int(round(r["avg_eng"] or 0)),
            "students_active": int(r["active_students"] or 0),
            "drowsy_alerts": int(r["drowsy_total"] or 0),
            "tab_switches": int(r["tab_total"] or 0),
        }
    })

@app.get("/api/lecturer/analytics/engagement_over_time")
def api_lecturer_engagement_over_time():
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    user_id = session["user_id"]

    session_id = (request.args.get("session_id") or "").strip()
    if not session_id.isdigit():
        return jsonify({"ok": False, "error": "missing_session_id"}), 400
    session_id = int(session_id)

    bucket_s = request.args.get("bucket_s", default=60, type=int)
    if bucket_s < 10 or bucket_s > 600:
        bucket_s = 60

    conn = connect()
    cur = conn.cursor()

    owns = cur.execute(
        """
        SELECT 1
        FROM sessions s
        JOIN classes c ON c.id = s.class_id
        WHERE s.id = ? AND c.owner_user_id = ?
        """,
        (session_id, user_id),
    ).fetchone()

    if not owns:
        conn.close()
        return jsonify({"ok": False, "error": "forbidden"}), 403

    rows = cur.execute(
        """
        SELECT ts, value
        FROM events
        WHERE session_id = ?
        ORDER BY ts ASC
        """,
        (session_id,),
    ).fetchall()

    conn.close()

    buckets = defaultdict(list)

    for r in rows:
        ts_iso = r["ts"] or ""
        try:
            dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        except Exception:
            continue

        try:
            v = json.loads(r["value"] or "{}")
        except Exception:
            v = {}

        # ✅ Use state_score (real signal). Fallback to score if needed.
        metric = v.get("state_score", None)
        if metric is None:
            metric = v.get("score", None)

        try:
            metric = float(metric)
        except Exception:
            continue

        epoch = int(dt.timestamp())
        bucket_epoch = (epoch // bucket_s) * bucket_s
        buckets[bucket_epoch].append(metric)

    labels = []
    values = []
    myt = timezone(timedelta(hours=8))

    sorted_keys = sorted(buckets.keys())
    if not sorted_keys:
        return jsonify({"ok": True, "bucket_s": bucket_s, "labels": [], "values": []})

    base = sorted_keys[0]  # first bucket time (start reference)

    for b in sorted_keys:
        arr = buckets[b]
        if not arr:
            continue

        avg = sum(arr) / len(arr)

        # ✅ elapsed minutes from start
        elapsed_min = int((b - base) / 60)
        labels.append(f"+{elapsed_min} min")

        values.append(round(avg, 2))

    return jsonify({
        "ok": True,
        "bucket_s": bucket_s,
        "labels": labels,
        "values": values,
    })

@app.get("/api/lecturer/analytics/engagement_by_student")
def api_lecturer_engagement_by_student():
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    user_id = session["user_id"]
    session_id = request.args.get("session_id", type=int)
    limit = request.args.get("limit", type=int)

    if not session_id:
        return jsonify({"ok": False, "error": "missing_session_id"}), 400

    conn = connect()
    cur = conn.cursor()

    owns = cur.execute(
        """
        SELECT 1
        FROM sessions s
        JOIN classes c ON c.id = s.class_id
        WHERE s.id = ? AND c.owner_user_id = ?
        """,
        (session_id, user_id),
    ).fetchone()

    if not owns:
        conn.close()
        return jsonify({"ok": False, "error": "forbidden"}), 403

    sql = """
        SELECT
          COALESCE(st.name, es.student_id) AS student_label,
          es.engagement_score AS engagement_score
        FROM engagement_summary es
        LEFT JOIN students st ON st.id = es.student_id
        WHERE es.session_id = ?
        ORDER BY es.engagement_score DESC
    """
    params = [session_id]

    if limit and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)

    rows = cur.execute(sql, params).fetchall()
    conn.close()

    return jsonify({
        "ok": True,
        "labels": [r["student_label"] for r in rows],
        "values": [int(r["engagement_score"] or 0) for r in rows]
    })

@app.get("/api/lecturer/analytics/state_breakdown")
def api_lecturer_state_breakdown():
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    user_id = session["user_id"]
    session_id = request.args.get("session_id", type=int)
    if not session_id:
        return jsonify({"ok": False, "error": "missing_session_id"}), 400

    conn = connect()
    cur = conn.cursor()

    # Ensure session belongs to lecturer
    owns = cur.execute(
        """
        SELECT 1
        FROM sessions s
        JOIN classes c ON c.id = s.class_id
        WHERE s.id = ? AND c.owner_user_id = ?
        """,
        (session_id, user_id),
    ).fetchone()

    if not owns:
        conn.close()
        return jsonify({"ok": False, "error": "forbidden"}), 403

    # Pull events and classify into 4 buckets
    rows = cur.execute(
        """
        SELECT type, value
        FROM events
        WHERE session_id = ?
        ORDER BY ts ASC
        """,
        (session_id,),
    ).fetchall()

    conn.close()

    counts = {"Attentive": 0, "Idle": 0, "Drowsy": 0, "Tab away": 0}

    for r in rows:
        etype = (r["type"] or "").lower()

        try:
            v = json.loads(r["value"] or "{}")
        except Exception:
            v = {}

        state = (v.get("state") or "").lower()  # e.g., "awake", "drowsy", "unknown"

        # Tab focus
        if etype == "tab_away":
            counts["Tab away"] += 1
            continue

        # Idle (from extension raw_type)
        if etype == "idle":
            counts["Idle"] += 1
            continue

        # Drowsy
        if etype == "drowsy" or state == "drowsy":
            counts["Drowsy"] += 1
            continue

        # Awake events can include Unknown state → treat Unknown as Idle
        if etype == "awake":
            if state == "unknown" or state == "":
                counts["Idle"] += 1
            else:
                counts["Attentive"] += 1
            continue

        # Other event types are ignored

    labels = ["Attentive", "Idle", "Drowsy", "Tab away"]
    values = [counts[l] for l in labels]

    return jsonify({"ok": True, "labels": labels, "values": values})

@app.get("/api/lecturer/analytics/engagement_extremes")
def api_lecturer_engagement_extremes():
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    user_id = session["user_id"]
    session_id = request.args.get("session_id", type=int)
    mode = request.args.get("mode", default="low")  # low | high

    if not session_id:
        return jsonify({"ok": False, "error": "missing_session_id"}), 400

    conn = connect()
    cur = conn.cursor()

    owns = cur.execute(
        """
        SELECT 1
        FROM sessions s
        JOIN classes c ON c.id = s.class_id
        WHERE s.id = ? AND c.owner_user_id = ?
        """,
        (session_id, user_id),
    ).fetchone()

    if not owns:
        conn.close()
        return jsonify({"ok": False, "error": "forbidden"}), 403

    order = "ASC" if mode == "low" else "DESC"

    rows = cur.execute(
        f"""
        SELECT
          COALESCE(st.name, es.student_id) AS student_label,
          es.engagement_score
        FROM engagement_summary es
        LEFT JOIN students st ON st.id = es.student_id
        WHERE es.session_id = ?
        ORDER BY es.engagement_score {order}
        LIMIT 5
        """,
        (session_id,),
    ).fetchall()

    conn.close()

    return jsonify({
        "ok": True,
        "labels": [r["student_label"] for r in rows],
        "values": [int(r["engagement_score"] or 0) for r in rows]
    })

@app.get("/api/lecturer/analytics/disengagement_cause_breakdown")
def api_lecturer_disengagement_cause_breakdown():
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    user_id = session["user_id"]
    session_id = request.args.get("session_id", type=int)
    if not session_id:
        return jsonify({"ok": False, "error": "missing_session_id"}), 400

    conn = connect()
    cur = conn.cursor()

    # Ownership check: make sure this session belongs to the lecturer's class
    owns = cur.execute(
        """
        SELECT 1
        FROM sessions s
        JOIN classes c ON c.id = s.class_id
        WHERE s.id = ? AND c.owner_user_id = ?
        """,
        (session_id, user_id),
    ).fetchone()

    if not owns:
        conn.close()
        return jsonify({"ok": False, "error": "forbidden"}), 403

    rows = cur.execute(
        """
        SELECT type, value
        FROM events
        WHERE session_id = ?
        ORDER BY ts ASC
        """,
        (session_id,),
    ).fetchall()

    conn.close()

    counts = {
        "Drowsiness": 0,
        "Tab switching": 0,
        "Inactivity / Unknown": 0,
        "Other": 0,
    }

    import json as _json

    for r in rows:
        etype = (r["type"] or "").strip().lower()

        # Parse JSON stored in value (your code stores a JSON dict there)
        state = ""
        try:
            payload = _json.loads(r["value"]) if r["value"] else {}
            state = (payload.get("state") or "").strip().lower()
        except Exception:
            state = ""

        # ---- Cause rules ----
        if etype == "drowsy" or state == "drowsy":
            counts["Drowsiness"] += 1
            continue

        if etype == "tab_away":
            counts["Tab switching"] += 1
            continue

        # Your existing logic treats awake + Unknown as idle-ish → we classify as inactivity/unknown
        if etype == "idle" or (etype == "awake" and (state == "unknown" or state == "")):
            counts["Inactivity / Unknown"] += 1
            continue

        # Optional bucket (keeps chart stable even if new event types appear)
        # If you prefer to ignore non-disengagement events like "awake"/"tab_back"/"sighting",
        # you can comment this out.
        if etype in ("tab_back", "awake", "sighting"):
            continue

        counts["Other"] += 1

    labels = ["Drowsiness", "Tab switching", "Inactivity / Unknown", "Other"]
    values = [counts[l] for l in labels]

    total = sum(values) or 1
    percentages = [round(v / total * 100.0, 1) for v in values]

    return jsonify({
        "ok": True,
        "labels": labels,
        "values": values,
        "percentages": percentages
    })

@app.get("/api/lecturer/analytics/risk_level_breakdown")
def api_risk_level_breakdown():
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    user_id = session["user_id"]
    session_id = request.args.get("session_id", type=int)
    if not session_id:
        return jsonify({"ok": False, "error": "missing_session_id"}), 400

    conn = connect()
    cur = conn.cursor()

    owns = cur.execute(
        """
        SELECT 1
        FROM sessions s
        JOIN classes c ON c.id = s.class_id
        WHERE s.id = ? AND c.owner_user_id = ?
        """,
        (session_id, user_id),
    ).fetchone()

    if not owns:
        conn.close()
        return jsonify({"ok": False, "error": "forbidden"}), 403

    rows = cur.execute(
        """
        SELECT engagement_score
        FROM engagement_summary
        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchall()

    conn.close()

    low = medium = high = 0

    for r in rows:
        score = r["engagement_score"]
        if score is None:
            continue

        # engagement_score is 0–100
        eng = max(0.0, min(1.0, float(score) / 100.0))
        risk = 1.0 - eng

        if risk <= RISK_LOW:
            low += 1
        elif risk <= RISK_MED:
            medium += 1
        else:
            high += 1

    return jsonify({
        "ok": True,
        "labels": ["Low", "Medium", "High"],
        "values": [low, medium, high],
        "thresholds": {
            "low": RISK_LOW,
            "medium": RISK_MED
        }
    })

# -------------------- API: Join Page (Student)--------------------
@app.post("/api/join/<class_id>")
def api_join_class(class_id):
    """
    Called by join.js when student submits the form.

    Body JSON:
      {
        "name": "...",
        "email": "...",
        "token": "...",        # optional
        "student_id": "S001"   # optional (from /api/identify)
      }
    """
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    token = (data.get("token") or request.args.get("token") or "").strip()
    student_id = (data.get("student_id") or "").strip()

    if not name or not email:
        return jsonify(
            {"ok": False, "error": "Please fill in your name and email."}
        ), 400

    # Optional: enforce join_token if set in DB
    if not verify_class_token(class_id, token):
        return jsonify(
            {"ok": False, "error": "Invalid or expired join link."}
        ), 403

    conn = connect()
    cur = conn.cursor()

    # --- make sure class exists, get platform_link if present ---
    try:
        class_row = cur.execute(
            "SELECT id, name, platform_link FROM classes WHERE id=?",
            (class_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        # fallback if platform_link column doesn't exist
        class_row = cur.execute(
            "SELECT id, name FROM classes WHERE id=?",
            (class_id,),
        ).fetchone()
        if class_row:
            class_row = dict(class_row)
            class_row["platform_link"] = None

    if not class_row:
        conn.close()
        return jsonify({"ok": False, "error": "Class not found."}), 404

    sid = None

    # 1) If camera already gave us a student_id, trust it (if exists)
    if student_id:
        row = cur.execute(
            "SELECT id FROM students WHERE id=?",
            (student_id,),
        ).fetchone()
        if row:
            sid = row["id"]

    # 2) Otherwise try reuse by email
    if not sid and email:
        row = cur.execute(
            "SELECT student_id FROM enrollments WHERE email=? "
            "ORDER BY id DESC LIMIT 1",
            (email,),
        ).fetchone()
        if row:
            sid = row["student_id"]

    # 3) Otherwise try reuse by name
    if not sid and name:
        row = cur.execute(
            "SELECT id FROM students WHERE name=? "
            "ORDER BY last_seen_ts DESC LIMIT 1",
            (name,),
        ).fetchone()
        if row:
            sid = row["id"]

    # 4) If still nothing, create brand new Sxxx student
    if not sid:
        sid = mint_next_student_id()
        cur.execute(
            "INSERT INTO students(id, name, embedding, last_seen_ts) "
            "VALUES (?,?,?,?)",
            (sid, name, None, now_iso()),
        )
    else:
        # If we have an existing student but name is empty/NULL, fill it
        cur.execute(
            """
            UPDATE students
            SET name = CASE
                         WHEN name IS NULL OR TRIM(name) = '' THEN ?
                         ELSE name
                       END
            WHERE id = ?
            """,
            (name, sid),
        )

    # 5) Upsert into enrollments for THIS class
    existing = cur.execute(
        "SELECT class_id, student_id FROM enrollments WHERE class_id=? AND student_id=?",
        (class_id, sid),
    ).fetchone()

    if existing:
        # Update same row using composite key (class_id, student_id)
        cur.execute(
            """
            UPDATE enrollments
            SET display_name = ?, email = ?
            WHERE class_id = ? AND student_id = ?
            """,
            (name, email, class_id, sid),
        )
    else:
        # Insert new enrollment
        cur.execute(
            """
            INSERT INTO enrollments(class_id, student_id, display_name, email)
            VALUES(?,?,?,?)
            """,
            (class_id, sid, name, email),
        )

    conn.commit()

    # Safe read of platform_link
    try:
        meet_link = class_row["platform_link"]
    except Exception:
        meet_link = None

    conn.close()

    return jsonify(
        {
            "ok": True,
            "class_id": class_id,
            "student_id": sid,
            "redirect_url": meet_link,
        }
    )

@app.get("/api/student_profile")
def api_student_profile():
    student_id = request.args.get("student_id", "").strip()
    class_id = request.args.get("class_id", "").strip()
    
    conn = connect(); cur = conn.cursor()
    
    # Check 1: Is already enrolled?
    row = cur.execute(
        "SELECT display_name, email FROM enrollments WHERE student_id=? AND class_id=?",
        (student_id, class_id)
    ).fetchone()
    
    if row:
        conn.close()
        return jsonify({
            "ok": True, 
            "exists": True, 
            "display_name": row["display_name"], 
            "email": row["email"]
        })

    # Check 2: Check Master Table
    row_stu = cur.execute("SELECT name FROM students WHERE id=?", (student_id,)).fetchone()
    conn.close()

    # THE CRITICAL FIX: Only lock if name is NOT empty
    if row_stu and row_stu["name"] and row_stu["name"].strip():
        return jsonify({
            "ok": True, 
            "exists": True,  # LOCKED
            "display_name": row_stu["name"], 
            "email": ""
        })
    else:
        # ID exists (Ghost user), so UNLOCK
        return jsonify({
            "ok": True, 
            "exists": False, # UNLOCKED
            "display_name": "", 
            "email": ""
        })

# -------------------- API: Summary & Attendance--------------------
@app.get("/api/summary/<class_id>/hero")
def api_summary_hero(class_id):
    """
    Numbers for the 3 hero cards on the class summary page:

      - total_students
      - avg_engagement
      - current_session_attendance
      - attendance_14w
    """
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    user_id = session["user_id"]

    conn = connect()
    cur = conn.cursor()

    # 1) Make sure this class belongs to the logged-in lecturer
    row = cur.execute(
        """
        SELECT id
        FROM classes
        WHERE id = ? AND owner_user_id = ?
        """,
        (class_id, user_id),
    ).fetchone()

    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "class_not_found"}), 404

    # 2) Total students (enrollments for this class)
    row = cur.execute(
        "SELECT COUNT(*) AS cnt FROM enrollments WHERE class_id = ?",
        (class_id,),
    ).fetchone()
    total_students = int(row["cnt"] or 0)

    # 3) Average engagement for this class (all sessions)
    row = cur.execute(
        """
        SELECT AVG(engagement_score) AS avg_score
        FROM engagement_summary
        WHERE class_id = ?
        """,
        (class_id,),
    ).fetchone()
    avg_eng = float(row["avg_score"] or 0.0)
    avg_eng_rounded = int(round(avg_eng))

    # 4) Current session attendance (latest open session for this class)
    row = cur.execute(
        """
        SELECT id
        FROM sessions
        WHERE class_id = ?
          AND end_ts IS NULL
        ORDER BY start_ts DESC
        LIMIT 1
        """,
        (class_id,),
    ).fetchone()

    current_attendance = None
    if row:
        current_session_id = row["id"]
        row_att = cur.execute(
            """
            SELECT
              SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present_cnt,
              COUNT(*) AS total_cnt
            FROM attendance
            WHERE session_id = ?
            """,
            (current_session_id,),
        ).fetchone()

        total_cnt = row_att["total_cnt"] or 0
        if total_cnt > 0:
            current_attendance = int(
                round(100.0 * (row_att["present_cnt"] or 0) / total_cnt)
            )

    # 5) 14-week attendance window for this class
    now = datetime.now(timezone.utc)
    cutoff_14w = now - timedelta(weeks=14)

    row_14 = cur.execute(
        """
        SELECT
          SUM(CASE WHEN a.status = 'present' THEN 1 ELSE 0 END) AS present_cnt,
          COUNT(*) AS total_cnt
        FROM attendance a
        JOIN sessions s ON a.session_id = s.id
        WHERE s.class_id = ?
          AND s.start_ts >= ?
        """,
        (class_id, cutoff_14w.isoformat()),
    ).fetchone()

    attendance_14w = None
    total_cnt_14 = row_14["total_cnt"] or 0
    if total_cnt_14 > 0:
        attendance_14w = int(
            round(100.0 * (row_14["present_cnt"] or 0) / total_cnt_14)
        )

    conn.close()

    return jsonify(
        {
            "ok": True,
            "class_id": class_id,
            "total_students": total_students,
            "avg_engagement": avg_eng_rounded,
            "current_session_attendance": current_attendance,
            "attendance_14w": attendance_14w,
        }
    )

@app.get("/api/summary/<class_id>/sessions")
def api_summary_sessions(class_id):
    """
    List sessions for a class (for the dropdown), newest first.
    Also returns which session should be selected by default.
    """
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    user_id = session["user_id"]

    conn = connect()
    cur = conn.cursor()

    # Make sure this class belongs to the logged-in lecturer
    row = cur.execute(
        """
        SELECT id
        FROM classes
        WHERE id = ? AND owner_user_id = ?
        """,
        (class_id, user_id),
    ).fetchone()

    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "class_not_found"}), 404

    rows = cur.execute(
        """
        SELECT id, name, start_ts, end_ts
        FROM sessions
        WHERE class_id = ?
        ORDER BY start_ts DESC
        LIMIT 40
        """,
        (class_id,),
    ).fetchall()

    sessions = []
    default_session_id = None

    for r in rows:
        start_ts = r["start_ts"]
        end_ts = r["end_ts"]
        is_open = end_ts is None

        # ⭐ Use the correct local-time formatter
        label = format_session_label(r)
        if is_open:
            label += " (live)"

        sessions.append(
            {
                "id": r["id"],
                "label": label,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "is_open": is_open,
            }
        )

        # default: prefer live session, otherwise first (newest)
        if default_session_id is None:
            default_session_id = r["id"]
        if is_open:
            default_session_id = r["id"]

    conn.close()

    return jsonify(
        {
            "ok": True,
            "class_id": class_id,
            "sessions": sessions,
            "default_session_id": default_session_id,
        }
    )

@app.get("/api/summary/<class_id>/session/<int:session_id>/engagement")
def api_summary_session_engagement(class_id, session_id):
    """
    Per-student engagement + attendance for one session in a class.
    Feeds the 'Student Engagement' table.

    Behaviour is derived from engagement_summary (drowsy_count, tab_away_count,
    idle_seconds) instead of raw events.
    """
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    user_id = session["user_id"]
    conn = connect()
    cur = conn.cursor()

    # Make sure this session belongs to this class AND to this lecturer
    row = cur.execute(
        """
        SELECT s.id
        FROM sessions s
        JOIN classes c ON s.class_id = c.id
        WHERE s.id = ? AND s.class_id = ? AND c.owner_user_id = ?
        """,
        (session_id, class_id, user_id),
    ).fetchone()

    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "not_found"}), 404

    # -------- Average engagement per student across all sessions in this class
    avg_eng_rows = cur.execute(
        """
        SELECT student_id, AVG(engagement_score) AS avg_eng
        FROM engagement_summary
        WHERE class_id = ?
        GROUP BY student_id
        """,
        (class_id,),
    ).fetchall()
    avg_eng_by_student = {
        r["student_id"]: (r["avg_eng"] or 0.0) for r in avg_eng_rows
    }

    # -------- Average attendance per student across all sessions in this class
    avg_att_rows = cur.execute(
        """
        SELECT
          a.student_id,
          SUM(CASE WHEN a.status = 'present' THEN 1 ELSE 0 END) AS present_cnt,
          COUNT(*) AS total_cnt
        FROM attendance a
        JOIN sessions s ON a.session_id = s.id
        WHERE s.class_id = ?
        GROUP BY a.student_id
        """,
        (class_id,),
    ).fetchall()

    avg_att_by_student = {}
    for r in avg_att_rows:
        total = r["total_cnt"] or 0
        if total > 0:
            pct = 100.0 * (r["present_cnt"] or 0) / total
        else:
            pct = None
        avg_att_by_student[r["student_id"]] = pct

    # -------- Main per-enrolment row for THIS session
    rows = cur.execute(
        """
        SELECT
          e.student_id,
          e.email,
          COALESCE(e.display_name, st.name, e.student_id) AS student_name,
          es.engagement_score AS session_engagement,
          es.risk_level       AS risk_level,
          es.drowsy_count     AS drowsy_count,
          es.tab_away_count   AS tab_away_count,
          es.idle_seconds     AS idle_seconds,
          att.status          AS attendance_status
        FROM enrollments e
        LEFT JOIN students st
               ON st.id = e.student_id
        LEFT JOIN engagement_summary es
               ON es.class_id = e.class_id
              AND es.session_id = ?
              AND es.student_id = e.student_id
        LEFT JOIN attendance att
               ON att.session_id = ?
              AND att.student_id = e.student_id
        WHERE e.class_id = ?
        ORDER BY e.display_name
        """,
        (session_id, session_id, class_id),
    ).fetchall()

    def _behaviour_from_summary(r):
        """Return nice multi-line HTML string for Behaviour column."""
        drowsy = int(r["drowsy_count"] or 0)
        tab_away = int(r["tab_away_count"] or 0)
        idle_seconds = int(r["idle_seconds"] or 0)

        # Fallback label based on risk level (when there are no counts)
        risk_map = {"low": "On track", "medium": "Monitor", "high": "At risk"}
        risk = (r["risk_level"] or "").lower() if r["risk_level"] else ""
        risk_label = risk_map.get(risk)

        lines = []

        if drowsy > 0:
            lines.append(f"Drowsy: {drowsy} time{'s' if drowsy != 1 else ''}")

        if tab_away > 0:
            lines.append(f"Tab away: {tab_away} time{'s' if tab_away != 1 else ''}")

        # OPTIONAL: keep idle if you like, or comment this block out
        if idle_seconds > 0:
            if idle_seconds >= 60:
                mins = round(idle_seconds / 60)
                lines.append(f"Idle: ~{mins} min")
            else:
                lines.append(f"Idle: {idle_seconds}s")

        # If we have any lines, join them with <br> for multi-line display.
        if lines:
            return "<br>".join(lines)

        # Otherwise, show simple risk label (On track / Monitor / At risk)
        return risk_label

    result_rows = []
    for r in rows:
        sid = r["student_id"]
        avg_eng = avg_eng_by_student.get(sid)
        avg_att_pct = avg_att_by_student.get(sid)

        behaviour_text = _behaviour_from_summary(r)

        result_rows.append(
            {
                "student_id": sid,
                "student_name": r["student_name"],
                "email": r["email"],
                "engagement_score": r["session_engagement"],
                "risk_level": r["risk_level"],
                "behaviour": behaviour_text,
                "attendance_status": r["attendance_status"],
                "average_engagement": None if avg_eng is None else round(avg_eng),
                "average_attendance": None
                if avg_att_pct is None
                else round(avg_att_pct),
            }
        )

    conn.close()

    return jsonify(
        {
            "ok": True,
            "class_id": class_id,
            "session_id": session_id,
            "rows": result_rows,
        }
    )

@app.get("/api/summary/<class_id>/engagement_csv")
def api_summary_engagement_csv(class_id):
    """
    CSV with TWO sections:

    1) SUMMARY PER STUDENT  (one row per student across all sessions)
    2) DETAILED ROWS PER SESSION (one row per session+student)

    So the lecturer only needs to download once.
    """
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    user_id = session["user_id"]
    conn = connect()
    cur = conn.cursor()

    # Make sure this class belongs to the logged-in lecturer
    owns = cur.execute(
        "SELECT 1 FROM classes WHERE id = ? AND owner_user_id = ?",
        (class_id, user_id),
    ).fetchone()
    if not owns:
        conn.close()
        return jsonify({"ok": False, "error": "forbidden"}), 403

    # ---- Fetch detailed rows ONCE ----
    rows = cur.execute(
        """
        SELECT
          es.session_id,
          s.start_ts,
          es.student_id,
          COALESCE(e.display_name, st.name, es.student_id) AS student_name,
          es.engagement_score,
          es.risk_level,
          es.drowsy_count,
          es.awake_count,
          es.tab_away_count,
          es.idle_seconds,
          att.status AS attendance_status
        FROM engagement_summary es
        JOIN sessions s
             ON s.id = es.session_id
        LEFT JOIN enrollments e
               ON e.class_id = es.class_id
              AND e.student_id = es.student_id
        LEFT JOIN students st
               ON st.id = e.student_id
        LEFT JOIN attendance att
               ON att.session_id = es.session_id
              AND att.student_id = es.student_id
        WHERE es.class_id = ?
        ORDER BY es.student_id, s.start_ts
        """,
        (class_id,),
    ).fetchall()

    conn.close()

    # ---- 1) Build summary stats per student ----
    stats = {}  # key = student_id

    for r in rows:
        sid = r["student_id"]
        stu = stats.setdefault(
            sid,
            {
                "student_name": r["student_name"] or sid,
                "sessions": 0,
                "eng_sum": 0.0,
                "eng_count": 0,
                "sessions_below_50": 0,
                "present": 0,
                "late": 0,
                "absent": 0,
                "att_total": 0,
            },
        )

        # engagement
        score = r["engagement_score"]
        if score is not None:
            score_f = float(score)
            stu["eng_sum"] += score_f
            stu["eng_count"] += 1
            stu["sessions"] += 1
            if score_f < 50.0:
                stu["sessions_below_50"] += 1

        # attendance
        status = (r["attendance_status"] or "").lower()
        if status in ("present", "late", "absent"):
            stu["att_total"] += 1
            if status == "present":
                stu["present"] += 1
            elif status == "late":
                stu["late"] += 1
            elif status == "absent":
                stu["absent"] += 1

    # ---- 2) Write combined CSV ----
    import io

    output = io.StringIO()
    writer = csv.writer(output)

    # ===== SECTION A: SUMMARY PER STUDENT =====
    writer.writerow(["SUMMARY PER STUDENT"])
    writer.writerow(
        [
            "class_id",
            "student_id",
            "student_name",
            "total_sessions",
            "average_engagement",    # %
            "sessions_below_50",
            "average_attendance",    # %
            "present_count",
            "late_count",
            "absent_count",
        ]
    )

    for sid, stu in stats.items():
        if stu["eng_count"] > 0:
            avg_eng = stu["eng_sum"] / stu["eng_count"]
        else:
            avg_eng = 0.0

        if stu["att_total"] > 0:
            avg_att = 100.0 * stu["present"] / stu["att_total"]
        else:
            avg_att = 0.0

        writer.writerow(
            [
                class_id,
                sid,
                stu["student_name"],
                stu["sessions"],
                f"{avg_eng:.1f}",
                stu["sessions_below_50"],
                f"{avg_att:.1f}",
                stu["present"],
                stu["late"],
                stu["absent"],
            ]
        )

    # blank lines between tables
    writer.writerow([])
    writer.writerow([])

    # ===== SECTION B: DETAILED ROWS PER SESSION =====
    writer.writerow(["DETAILED ROWS PER SESSION"])
    writer.writerow(
        [
            "class_id",
            "session_id",
            "session_start_utc",
            "student_id",
            "student_name",
            "engagement_score",
            "risk_level",
            "drowsy_count",
            "awake_count",
            "tab_away_count",
            "idle_seconds",
            "attendance_status",
        ]
    )

    for r in rows:
        writer.writerow(
            [
                class_id,
                r["session_id"],
                r["start_ts"],
                r["student_id"],
                r["student_name"],
                r["engagement_score"],
                r["risk_level"],
                r["drowsy_count"],
                r["awake_count"],
                r["tab_away_count"],
                r["idle_seconds"],
                r["attendance_status"],
            ]
        )

    csv_data = output.getvalue()
    output.close()

    resp = make_response(csv_data)
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers[
        "Content-Disposition"
    ] = f"attachment; filename=class_{class_id}_engagement_full.csv"
    return resp

@app.post("/api/summary/<class_id>/session/<int:session_id>/attendance_override")
def api_attendance_override(class_id, session_id):
    """
    Manually override attendance.status for one student in one session.
    Body JSON: { "student_id": "...", "status": "present" | "late" | "absent" }

    After updating attendance we recompute engagement_summary for this session
    so overrides are reflected in KPIs.
    """
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    user_id = session["user_id"]
    payload = request.get_json(silent=True) or {}
    student_id = (payload.get("student_id") or "").strip()
    status = (payload.get("status") or "").strip().lower()

    if not student_id or status not in ("present", "late", "absent"):
        return jsonify({"ok": False, "error": "bad_request"}), 400

    conn = connect()
    cur = conn.cursor()

    # Check session + class belongs to this lecturer
    row = cur.execute(
        """
        SELECT s.id
        FROM sessions s
        JOIN classes c ON s.class_id = c.id
        WHERE s.id = ? AND s.class_id = ? AND c.owner_user_id = ?
        """,
        (session_id, class_id, user_id),
    ).fetchone()

    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "not_found"}), 404

    # Upsert into attendance
    existing = cur.execute(
        """
        SELECT id FROM attendance
        WHERE session_id = ? AND student_id = ?
        """,
        (session_id, student_id),
    ).fetchone()

    now_ts = now_iso()

    if existing:
        cur.execute(
            "UPDATE attendance SET status=? WHERE id=?",
            (status, existing["id"]),
        )
    else:
        # first_seen_ts / last_seen_ts just set to now for manual overrides
        cur.execute(
            """
            INSERT INTO attendance (session_id, student_id, status, first_seen_ts, last_seen_ts)
            VALUES (?,?,?,?,?)
            """,
            (session_id, student_id, status, now_ts, now_ts),
        )

    conn.commit()
    conn.close()

    # Recompute engagement_summary so "absent=0 score" etc reflect override
    try:
        compute_engagement_for_session(session_id)
    except Exception as e:
        print("[override] recompute engagement failed:", e, file=sys.stderr)

    return jsonify({"ok": True, "student_id": student_id, "status": status})

@app.patch("/api/classes/<class_id>/enrollment/<student_id>")
def api_update_enrollment(class_id, student_id):
    """
    Update display_name / email for one enrollment.
    Body: { "display_name": "...", "email": "..." }
    """
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}
    display_name = data.get("display_name")
    email = data.get("email")

    conn = connect()
    cur = conn.cursor()

    # Owns this class?
    row = cur.execute(
        "SELECT id FROM classes WHERE id=? AND owner_user_id=?",
        (class_id, user_id),
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "class_not_found"}), 404

    cur.execute(
        """
        UPDATE enrollments
        SET display_name = COALESCE(?, display_name),
            email        = COALESCE(?, email)
        WHERE class_id = ? AND student_id = ?
        """,
        (display_name, email, class_id, student_id),
    )

    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.delete("/api/classes/<class_id>/enrollment/<student_id>")
def api_delete_enrollment(class_id, student_id):
    """
    Remove a student from a class (delete enrollment row).
    """
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    user_id = session["user_id"]

    conn = connect()
    cur = conn.cursor()

    # Owns this class?
    row = cur.execute(
        "SELECT id FROM classes WHERE id=? AND owner_user_id=?",
        (class_id, user_id),
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "class_not_found"}), 404

    cur.execute(
        "DELETE FROM enrollments WHERE class_id=? AND student_id=?",
        (class_id, student_id),
    )

    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# -------------------- API: Auto session_from_meet --------------------
@app.post("/api/auto/session_from_meet")
def api_auto_session_from_meet():
    """
    The extension calls this once per Meet tab to get/create a session.
    Payload (from extension):
      { "course_id": "CSC4400", "meet_url": "...", "title": "..." }
    """
    data = request.get_json(force=True, silent=True) or {}

    # Treat course_id as our class_id
    class_id = (data.get("course_id") or "CS101").strip()
    meet_url = (data.get("meet_url") or "").strip()
    title    = (data.get("title") or "").strip() or f"Meet - {class_id}"

    conn = connect(); cur = conn.cursor()

    # Try to reuse an open session for the same class + meet link
    row = cur.execute(
        """
        SELECT id
        FROM sessions
        WHERE class_id=? AND platform_link=? AND end_ts IS NULL
        ORDER BY start_ts DESC
        LIMIT 1
        """,
        (class_id, meet_url),
    ).fetchone()

    if row:
        session_id = row["id"]
    else:
        # Store class_id + meet_url so later we can aggregate correctly
        cur.execute(
            """
            INSERT INTO sessions(name, start_ts, class_id, platform_link)
            VALUES (?,?,?,?)
            """,
            (title, now_iso(), class_id, meet_url),
        )
        session_id = cur.lastrowid

    conn.commit()
    conn.close()

    return jsonify({"ok": True, "session_id": session_id})

# -------------------- API: Stop session --------------------
@app.post("/stop")
def api_session_stop():
    """
    Called by the extension when the lecturer clicks Stop.
    Payload (JSON or Beacon body):
      { "session_id": <id> }  (optional)
    If session_id is missing, we just close the latest open session.
    """
    data = None
    try:
        # For normal fetch/post
        data = request.get_json(silent=True)
    except Exception:
        data = None

    if not data:
        # For sendBeacon, body is raw bytes, but Flask already parsed if possible;
        # if not, we just close the latest open session.
        data = {}

    sid = data.get("session_id")
    try:
        sid = int(sid) if sid is not None else None
    except Exception:
        sid = None

    conn = connect(); cur = conn.cursor()

    # If no id given, use latest open session (if any)
    if not sid:
        row = cur.execute(
            "SELECT id FROM sessions WHERE end_ts IS NULL "
            "ORDER BY start_ts DESC LIMIT 1"
        ).fetchone()
        if row:
            sid = row["id"]
        else:
            conn.close()
            return jsonify({"ok": True, "session_id": None})

    cur.execute(
        "UPDATE sessions SET end_ts=? WHERE id=? AND end_ts IS NULL",
        (now_iso(), sid),
    )
    conn.commit()
    conn.close()

    # NEW: aggregate raw events into engagement_summary
    try:
        compute_engagement_for_session(sid)
    except Exception as e:
        print("[engagement_summary] compute failed:", e, file=sys.stderr)

    return jsonify({"ok": True, "session_id": sid})

# -------------------- API: Sighting (Python vision loop) --------------------
@app.post("/api/sighting")
def api_sighting():
    """Called by vision/run_loop.py for every sighting (throttled there)."""
    data = request.get_json(force=True, silent=True) or {}
    course_id = data.get("course_id", "CS101")
    name      = data.get("name", "UNKNOWN")
    score     = float(data.get("score", 0.0))
    camera_id = data.get("camera_id", "CAM1")
    ts        = float(data.get("ts", _now()))

    # Drop unknowns so they never show up in /api/seen
    if name.upper() == "UNKNOWN" or name.lower().startswith("unknown"):
        return jsonify({"ok": True, "ignored": "unknown"}), 200

    key = (course_id, name)
    row = SEEN.get(key)
    if row is None:
        row = {
            "first_seen": ts,
            "last_seen": ts,
            "count": 1,
            "camera_id": camera_id,
            "score": score,
        }
        SEEN[key] = row
    else:
        row["last_seen"] = ts
        row["count"] += 1
        row["camera_id"] = camera_id
        row["score"] = score

    conn = connect(); cur = conn.cursor()

    session_id = (data.get("session_id") if isinstance(data, dict) else None)
    try:
        session_id = int(session_id) if session_id is not None else None
    except Exception:
        session_id = None

    if session_id:
        r = cur.execute(
            "SELECT id FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        if not r:
            session_id = None
    if not session_id:
        session_id = get_open_session_id(conn)
        if not session_id:
            cur.execute(
                "INSERT INTO sessions(name, start_ts) VALUES(?,?)",
                ("Auto Session", now_iso()),
            )
            session_id = cur.lastrowid

    # Find or create student by NAME
    row2 = cur.execute(
        "SELECT id FROM students WHERE name=?", (name,)
    ).fetchone()
    if row2:
        sid = row2["id"]
    else:
        row_max = cur.execute(
            "SELECT id FROM students WHERE id LIKE 'S%%' "
            "ORDER BY CAST(SUBSTR(id,2) AS INTEGER) DESC LIMIT 1"
        ).fetchone()
        next_num = (int(row_max["id"][1:]) + 1) if row_max else 1
        sid = f"S{next_num:03d}"
        cur.execute(
            "INSERT INTO students(id, name, embedding, last_seen_ts) "
            "VALUES(?,?,?,?)",
            (sid, name, None, datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()),
        )

    value = {
        "score": score,
        "camera_id": camera_id,
        "from": "python_loop",
    }
    exec_retry(
        cur,
        "INSERT INTO events(session_id, student_id, type, value, ts) "
        "VALUES(?,?,?,?,?)",
        (
            session_id,
            sid,
            "sighting",
            json.dumps(value),
            datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
        ),
    )

    try:
        mark_attendance_if_needed(
            conn, session_id, sid, now_iso()
        )
    except Exception as e:
        print("[attendance] mark failed:", e, file=sys.stderr)

    conn.commit(); conn.close()

    try:
        socketio.emit(
            "sighting",
            {
                "course_id": course_id,
                "name": name,
                "score": score,
                "camera_id": camera_id,
                "last_seen": row["last_seen"],
                "count": row["count"],
            },
        )
    except Exception:
        pass

    return jsonify({"ok": True})

# -------------------- API: Seen --------------------
@app.get("/api/seen")
def api_seen():
    """Return a flat list for the dashboard."""
    course = request.args.get("course_id", "CS101")
    rows = []
    for (course_id, name), v in SEEN.items():
        if course_id != course:
            continue
        rows.append(
            {
                "name": name,
                "camera_id": v.get("camera_id"),
                "score": round(float(v.get("score", 0.0)), 3),
                "count": int(v.get("count", 0)),
                "first_seen": v.get("first_seen"),
                "last_seen": v.get("last_seen"),
            }
        )
    rows.sort(key=lambda r: r["last_seen"], reverse=True)
    return jsonify({"ok": True, "rows": rows})

@app.post("/api/reset_seen")
def api_reset_seen():
    """Clear memory (handy for testing)."""
    SEEN.clear()
    return jsonify({"ok": True})

# -------------------- API: Events --------------------
@app.get("/api/events")
def recent_events():
    """
    Query params:
      limit=1000
      student_id=S001
      session_id=5
      type=awake
      since_minutes=10
    """
    limit = int(request.args.get("limit", 100))
    student_id = request.args.get("student_id")
    session_id = request.args.get("session_id")
    etype = request.args.get("type")
    since_minutes = request.args.get("since_minutes")

    q = "SELECT id, session_id, student_id, type, value, ts FROM events WHERE 1=1"
    args = []

    if student_id:
        q += " AND student_id=?"; args.append(student_id)
    if session_id:
        q += " AND session_id=?"; args.append(session_id)
    if etype:
        q += " AND type=?"; args.append(etype)
    if since_minutes:
        try:
            mins = int(since_minutes)
            cutoff = (
                datetime.now(timezone.utc) - timedelta(minutes=mins)
            ).isoformat()
            q += " AND ts >= ?"; args.append(cutoff)
        except Exception:
            pass

    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)

    conn = connect(); cur = conn.cursor()
    rows = cur.execute(q, args).fetchall()
    conn.close()

    out = []
    for r in rows:
        try:
            val = json.loads(r["value"]) if r["value"] else None
        except Exception:
            val = None
        out.append(
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "student_id": r["student_id"],
                "type": r["type"],
                "value": val,
                "ts": r["ts"],
            }
        )
    return jsonify({"ok": True, "events": out})

@app.post("/api/events")
def create_event():
    """
    Called by extension for each detection state.
    Payload (JSON):
      {
        course_id, camera_id, name, student_id?, score?,
        state?, state_score?, bbox?, ts?, type?, value?, is_lecturer?
      }
    """
    from datetime import datetime, timezone
    import time as _time

    data = request.get_json(force=True, silent=True) or {}

    required = ["course_id", "camera_id", "name", "ts"]
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({"ok": False, "error": f"missing fields: {', '.join(missing)}"}), 400

    student_id   = (data.get("student_id") or "").strip()
    display_name = (data.get("name") or "").strip()
    state        = (data.get("state") or "").strip() or None
    state_score  = float(data.get("state_score", 0.0) or 0.0)
    score        = float(data.get("score", 0.0) or 0.0)
    bbox         = data.get("bbox") or {}
    ts_epoch     = float(data.get("ts", _time.time()))
    ts_iso       = datetime.fromtimestamp(ts_epoch, tz=timezone.utc).isoformat()

    if not student_id and (
        display_name.upper() == "UNKNOWN"
        or display_name.lower().startswith("unknown")
    ):
        return jsonify({"ok": True, "ignored": "unknown"}), 200

    if not student_id and display_name:
        conn = connect(); cur = conn.cursor()

        row = cur.execute(
            "SELECT id FROM students WHERE name=?", (display_name,)
        ).fetchone()
        if row:
            student_id = row["id"]
        else:
            row = cur.execute(
                "SELECT id FROM students WHERE id LIKE 'S%%' "
                "ORDER BY CAST(SUBSTR(id,2) AS INTEGER) DESC LIMIT 1"
            ).fetchone()
            next_num = (int(row["id"][1:]) if row else 0) + 1
            student_id = f"S{next_num:03d}"

            cur.execute(
                "INSERT INTO students(id, name, embedding, last_seen_ts) "
                "VALUES(?,?,?,?)",
                (student_id, display_name, None, datetime.now(timezone.utc).isoformat()),
            )

        conn.commit(); conn.close()

    # Decide the event type stored in events.type
    raw_type = (data.get("type") or "").strip().lower()

    if raw_type:
        # For things like "tab_away", "tab_back", "idle", "lecturer_toggle", ...
        etype = raw_type
    elif state:
        # Normal detector events: drowsy / awake
        etype = "drowsy" if state.lower() == "drowsy" else "awake"
    else:
        # Fallback
        etype = "sighting"

    value = {
        "score": score,
        "state": state,
        "state_score": state_score,
        "camera_id": data.get("camera_id"),
        "bbox": {
            "x": int(bbox.get("x", 0)),
            "y": int(bbox.get("y", 0)),
            "w": int(bbox.get("w", 0)),
            "h": int(bbox.get("h", 0)),
        },
        "name": display_name,
        "raw_type": raw_type,           # normalized type
        "raw_value": data.get("value"), # your custom value (e.g. idle duration)
        "is_lecturer": bool(data.get("is_lecturer")),
    }

    conn = connect(); cur = conn.cursor()

    session_id = data.get("session_id")
    try:
        session_id = int(session_id) if session_id is not None else None
    except Exception:
        session_id = None

    if session_id:
        r = cur.execute(
            "SELECT id FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        if not r:
            session_id = None
    if not session_id:
        session_id = get_open_session_id(conn)
        if not session_id:
            cur.execute(
                "INSERT INTO sessions(name, start_ts) VALUES(?,?)",
                ("Auto Session", now_iso()),
            )
            session_id = cur.lastrowid

    try:
        cur.execute(
            "UPDATE students SET last_seen_ts=? WHERE id=?",
            (ts_iso, student_id),
        )
    except Exception:
        pass

    exec_retry(
        cur,
        "INSERT INTO events(session_id, student_id, type, value, ts) "
        "VALUES(?,?,?,?,?)",
        (session_id, student_id, etype, json.dumps(value), ts_iso),
    )
    event_id = cur.lastrowid

    try:
        mark_attendance_if_needed(conn, session_id, student_id, ts_iso)
    except Exception as e:
        print("[attendance] mark failed:", e, file=sys.stderr)

    conn.commit(); conn.close()

    out = {
        "id": event_id,
        "session_id": session_id,
        "student_id": student_id,
        "type": etype,
        "value": value,
        "ts": ts_iso,
    }
    socketio.emit("event", out, namespace="/events")
    return jsonify({"ok": True, "event_id": event_id, "session_id": session_id})

# -------------------- API: Infer (state only) --------------------
@app.post("/api/infer")
def api_infer():
    f = request.files.get("frame")
    if not f:
        return jsonify({"ok": False, "error": "no frame"}), 400

    file_bytes = np.frombuffer(f.read(), np.uint8)
    img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    if img is None:
        return jsonify({"ok": False, "error": "bad image"}), 400

    det = get_detector()
    dets = det.predict_states(img)

    if not dets:
        return jsonify({"ok": True, "state": "Unknown", "state_score": 0.0, "bbox": None})

    # --- normalize to list ---
    if isinstance(dets, dict):
        dets = [dets]

    def to_bucket(label: str) -> str:
        s = (label or "").strip().lower()
        # map many possible model outputs -> Drowsy
        if ("drow" in s) or ("sleep" in s) or ("yawn" in s) or ("close" in s) or ("fatigue" in s) or ("tired" in s):
            return "Drowsy"
        if ("awake" in s) or ("alert" in s) or ("normal" in s) or ("open" in s):
            return "Awake"
        return "Unknown"

    # find best Awake / Drowsy candidate (by score)
    best_awake = None
    best_drowsy = None
    best_any = None

    for d in dets:
        if "score" not in d:
            continue
        if best_any is None or d["score"] > best_any["score"]:
            best_any = d

        bucket = to_bucket(d.get("label", ""))
        if bucket == "Awake":
            if best_awake is None or d["score"] > best_awake["score"]:
                best_awake = d
        elif bucket == "Drowsy":
            if best_drowsy is None or d["score"] > best_drowsy["score"]:
                best_drowsy = d

    if best_any is None:
        return jsonify({"ok": True, "state": "Unknown", "state_score": 0.0, "bbox": None})

    # --- decision rules ---
    # Make Drowsy easier to show (because models often bias to Awake)
    DROWSY_MIN = 0.55
    MARGIN = 0.08  # if drowsy is close to awake, prefer drowsy

    chosen = best_any
    if best_drowsy and best_drowsy["score"] >= DROWSY_MIN:
        if (best_awake is None) or (best_drowsy["score"] >= best_awake["score"] - MARGIN):
            chosen = best_drowsy

    # bbox safely (some models might not return xyxy)
    bbox = None
    if chosen.get("xyxy") and len(chosen["xyxy"]) == 4:
        x1, y1, x2, y2 = chosen["xyxy"]
        bbox = {"x": int(x1), "y": int(y1), "w": int(x2 - x1), "h": int(y2 - y1)}

    # output normalized state label
    state = to_bucket(chosen.get("label", ""))
    score = float(chosen.get("score", 0.0))

    return jsonify({"ok": True, "state": state, "state_score": score, "bbox": bbox})

# -------------------- API: Identify (single face) --------------------
@app.post("/api/identify")
def api_identify():
    print("=== IDENTIFY DEBUG ===")
    print("content_type:", request.content_type)
    print("files:", list(request.files.keys()))
    print("form:", dict(request.form))

    """
    Expect: multipart/form-data with frame=<jpeg>
    Return: { ok, student_id, name, sim, bbox, pending }
            - pending=True while confirming a NEW face
    """

    # ---------- 1) Get uploaded image & decode safely ----------
    file = (
        request.files.get("frame")
        or request.files.get("image")
        or request.files.get("file")
    )
    if file is None:
        print("identify: no file field found")
        return jsonify(ok=False, error="no frame"), 400

    data = file.read()
    print("identify: got", len(data), "bytes")

    if not data:
        print("identify: empty image data")
        return jsonify(ok=False, error="empty image"), 400

    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    if img is None:
        # Save debug file so we can inspect what was received
        ts = int(time.time())
        debug_path = os.path.join(
            os.path.dirname(__file__),
            f"debug_bad_frame_{ts}.jpg",
        )
        with open(debug_path, "wb") as f:
            f.write(data)
        print("identify: imdecode failed, saved debug to", debug_path)
        return jsonify(ok=False, error="bad image"), 400

    # ---------- 2) Find largest face ----------
    bbox = find_largest_face_bbox(img)
    if not bbox:
        return jsonify(
            {
                "ok": True,
                "student_id": None,
                "name": None,
                "sim": pfloat(0.0),
                "bbox": None,
                "pending": False,
            }
        )

    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    bbox_json = {"x": pint(x1), "y": pint(y1), "w": pint(w), "h": pint(h)}

    # ---------- 3) Basic quality checks ----------
    MIN_FACE_W = 70
    MIN_FACE_H = 70
    if w < MIN_FACE_W or h < MIN_FACE_H:
        return jsonify(
            {
                "ok": True,
                "student_id": None,
                "name": None,
                "sim": pfloat(0.0),
                "bbox": bbox_json,
                "pending": True,
            }
        )

    face_gray = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    if cv2.Laplacian(face_gray, cv2.CV_64F).var() < 30:
        # too blurry
        return jsonify(
            {
                "ok": True,
                "student_id": None,
                "name": None,
                "sim": pfloat(0.0),
                "bbox": bbox_json,
                "pending": True,
            }
        )

    # ---------- 4) Embed face ----------
    emb_factory = get_embedder()
    res = emb_factory.embed(img[y1:y2, x1:x2])
    if not res.ok:
        return jsonify(
            {
                "ok": True,
                "student_id": None,
                "name": None,
                "sim": pfloat(0.0),
                "bbox": bbox_json,
                "pending": False,
            }
        )

    q = np.asarray(res.emb, dtype=np.float32)

    # ---------- 5) Compare with existing students ----------
    conn = connect()
    cur = conn.cursor()
    # -------------------- Restrict matching by class (via session_id) --------------------
    session_id = request.args.get("session_id", type=int)
    class_id = None

    if session_id:
        try:
            r_sess = cur.execute(
                "SELECT class_id FROM sessions WHERE id=?",
                (session_id,),
            ).fetchone()
            if r_sess and r_sess.get["class_id"]:
                class_id = r_sess["class_id"]
        except Exception:
            class_id = None

    # If we have class_id, only compare against students enrolled in that class
    if class_id:
        rows = cur.execute(
            """
            SELECT
              s.id AS id,
              COALESCE(e.display_name, s.name) AS name,
              s.embedding AS embedding
            FROM enrollments e
            JOIN students s ON s.id = e.student_id
            WHERE e.class_id = ?
            """,
            (class_id,),
        ).fetchall()
    else:
        # fallback: old behavior (all students)
        rows = cur.execute("SELECT id, name, embedding FROM students").fetchall()

    best_sid, best_name, best_sim = None, None, -1.0
    for r in rows:
        if not r["embedding"]:
            continue
        try:
            v = np.asarray(json.loads(r["embedding"]), dtype=np.float32)
            s = cos_sim(q, v)
            if s > best_sim:
                best_sid, best_name, best_sim = r["id"], r["name"], s
        except Exception:
            pass

    sim_val = float(best_sim if best_sim is not None else 0.0)

    # ---------- 6) Known face above threshold ----------
    if best_sid and sim_val >= SIM_THRESHOLD:
        try:
            merge_embedding_into(conn, best_sid, q)
        except Exception:
            pass
        try:
            cur.execute(
                "UPDATE students SET last_seen_ts=? WHERE id=?",
                (now_iso(), best_sid),
            )
            conn.commit()
        except Exception:
            pass
        conn.close()
        return jsonify(
            {
                "ok": True,
                "pending": False,
                "student_id": best_sid,
                "name": best_name,
                "sim": sim_val,
                "bbox": bbox_json,
            }
        )

    # ---------- 7) If session_id/class_id is present, DO NOT create new student ----------
    if class_id:
        conn.close()
        return jsonify(
            {
                "ok": True,
                "pending": False,
                "student_id": None,
                "name": "Unknown",
                "sim": sim_val,
                "bbox": bbox_json,
            }
        )

    # ---------- 8) Handle NEW face with pending window (only when class_id is NOT known) ----------
    t = time.time()
    camera_id = (request.form.get("camera_id") or "MEET_TAB").strip()
    st = PENDING_STATE.setdefault(camera_id, {"n": 0, "t0": t})
    if t - st["t0"] > NEW_CONFIRM_WINDOW_S:
        st["n"] = 0
        st["t0"] = t
    st["n"] += 1

    if st["n"] >= NEW_CONFIRM_FRAMES:
        # Confirm as a new student
        new_id = mint_next_student_id()
        try:
            cur.execute(
                "INSERT INTO students(id, name, embedding, last_seen_ts) "
                "VALUES (?,?,?,?)",
                (new_id, None, json.dumps(q.tolist()), now_iso()),
            )
            conn.commit()
        finally:
            conn.close()

        PENDING_STATE.pop(camera_id, None)

        return jsonify(
            {
                "ok": True,
                "pending": False,
                "student_id": new_id,
                "name": None,
                "sim": sim_val,
                "bbox": bbox_json,
            }
        )

    # Still pending (face seen but not enough frames yet)
    conn.close()
    return jsonify(
        {
            "ok": True,
            "pending": True,
            "student_id": None,
            "name": None,
            "sim": sim_val,
            "bbox": bbox_json,
        }
    )

# -------------------- API: Identify Multi (multi-person) --------------------
@app.post("/api/identify_multi")
def api_identify_multi():
    """
    multipart/form-data: frame=<jpeg>
    -> { ok, faces: [ {student_id, name, sim, bbox:{x,y,w,h}, pending} ] }
    Processes ALL detected faces, not just the largest.
    """
    f = request.files.get("frame")
    if not f:
        return jsonify({"ok": False, "error": "no frame"}), 400

    file_bytes = np.frombuffer(f.read(), np.uint8)
    img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    if img is None:
        return jsonify({"ok": False, "error": "bad image"}), 400

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)

    h, w = gray.shape[:2]
    if max(h, w) < 640:
        scale = 640.0 / max(h, w)
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)))

    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    params_list = [
        dict(scaleFactor=1.03, minNeighbors=3, minSize=(32, 32)),
        dict(scaleFactor=1.05, minNeighbors=3, minSize=(40, 40)),
        dict(scaleFactor=1.08, minNeighbors=3, minSize=(50, 50)),
        dict(scaleFactor=1.10, minNeighbors=4, minSize=(60, 60)),
    ]
    faces = []
    for p in params_list:
        fs = cascade.detectMultiScale(gray, **p)
        if len(fs):
            faces = fs
            break

    out = []
    if not len(faces):
        return jsonify({"ok": True, "faces": out})

    emb_factory = get_embedder()
    conn = connect(); cur = conn.cursor()
    rows = cur.execute("SELECT id, name, embedding FROM students").fetchall()

    def best_match(qvec):
        best_sid, best_name, best_sim = None, None, -1.0
        for r in rows:
            if not r["embedding"]:
                continue
            try:
                v = np.asarray(json.loads(r["embedding"]), dtype=np.float32)
                s = cos_sim(qvec, v)
                if s > best_sim:
                    best_sid, best_name, best_sim = r["id"], r["name"], s
            except Exception:
                continue
        return best_sid, best_name, float(best_sim)

    MIN_FACE = 48
    for (x, y, w, h) in faces:
        bbox_json = {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
        if w < MIN_FACE or h < MIN_FACE:
            out.append(
                {
                    "student_id": None,
                    "name": None,
                    "sim": 0.0,
                    "bbox": bbox_json,
                    "pending": True,
                }
            )
            continue

        crop = img[y:y+h, x:x+w]
        face_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        if cv2.Laplacian(face_gray, cv2.CV_64F).var() < 40:
            out.append(
                {
                    "student_id": None,
                    "name": None,
                    "sim": 0.0,
                    "bbox": bbox_json,
                    "pending": True,
                }
            )
            continue

        res = emb_factory.embed(crop)
        if not res.ok:
            out.append(
                {
                    "student_id": None,
                    "name": None,
                    "sim": 0.0,
                    "bbox": bbox_json,
                    "pending": False,
                }
            )
            continue

        q = np.asarray(res.emb, dtype=np.float32)
        best_sid, best_name, best_sim = best_match(q)
        sim_val = float(best_sim if best_sim is not None else 0.0)

        if sim_val >= AMBIG_THR and sim_val < SIM_THRESHOLD:
            out.append(
                {
                    "student_id": None,
                    "name": None,
                    "sim": sim_val,
                    "bbox": bbox_json,
                    "pending": True,
                }
            )
        elif best_sid and sim_val >= SIM_THRESHOLD:
            try:
                merge_embedding_into(conn, best_sid, q)
            except Exception:
                pass
            out.append(
                {
                    "student_id": best_sid,
                    "name": best_name,
                    "sim": sim_val,
                    "bbox": bbox_json,
                    "pending": False,
                }
            )
        else:
            out.append(
                {
                    "student_id": None,
                    "name": None,
                    "sim": sim_val,
                    "bbox": bbox_json,
                    "pending": False,
                }
            )

    conn.close()
    return jsonify({"ok": True, "faces": out})

# -------------------- API: Live roster --------------------
@app.get("/api/live")
def api_live():
    LIVE_WINDOW_S = 180
    try:
        from datetime import datetime, timezone

        session_id = request.args.get("session_id", type=int)
        conn = connect(); cur = conn.cursor()

        if not session_id:
            row = cur.execute(
                "SELECT id FROM sessions WHERE end_ts IS NULL "
                "ORDER BY start_ts DESC LIMIT 1"
            ).fetchone()
            if not row:
                conn.close()
                return jsonify({"ok": True, "students": [], "session_id": None})
            session_id = row["id"]

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=LIVE_WINDOW_S)

        rows = cur.execute(
            """
            SELECT e.student_id, e.ts, e.type, e.value, s.name
            FROM events e
            LEFT JOIN students s ON s.id = e.student_id
            WHERE e.session_id=? AND e.ts >= ?
            ORDER BY e.ts DESC
            """,
            (session_id, cutoff.isoformat()),
        ).fetchall()
        conn.close()

        latest = {}
        for r in rows:
            sid = r["student_id"]
            if not sid:
                continue
            if sid in latest:
                continue

            try:
                val = json.loads(r["value"]) if r["value"] else {}
            except Exception:
                val = {}

            state = (val.get("state") or "").lower()
            state_score = val.get("state_score", 0.0)
            raw_type = (r["type"] or "").lower()

            # ---- status label for Live Roster ----
            if raw_type == "drowsy":
                status = "Drowsy"
            elif raw_type == "awake":
                status = "Awake"
            elif raw_type == "tab_away":
                status = "Away"
            else:
                # default if we only know they are in the window
                status = "Present"

            latest[sid] = {
                "student_id": sid,
                "name": r["name"] or sid,
                "status": status,
                "last_seen": r["ts"],
                "state": state,
                "state_score": state_score,
            }

        return jsonify(
            {
                "ok": True,
                "students": list(latest.values()),
                "session_id": session_id,
            }
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# -------------------- Socket.IO --------------------
@socketio.on("connect", namespace="/events")
def on_connect_events():
    emit("connected", {"ok": True})

# -------------------- Main --------------------
print("Running app from:", __file__)
print("Registered routes at startup:")
print(app.url_map)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    socketio.run(app, host="0.0.0.0", port=port, debug=True)
