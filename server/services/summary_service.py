from datetime import datetime, timezone
from collections import defaultdict

# ---- Replace these with your real integrations ----
def load_roster(course_id: str):
    """
    Read your gallery/students list.
    Return list of dicts: {"id":"S001","name":"Hannis"}
    """
    return []

def load_events_for_window(course_id: str, start: datetime, end: datetime):
    """
    Query your DB/events store.
    Return list of dicts:
      {"ts": ISO8601, "student_id":"S001", "type":"idle|tab_away|yawn|left_frame|awake",
       "value": float?, "duration_s": int?}
    """
    return []

def compute_summary_payload(course_id: str, start: datetime, end: datetime, window_label: str = "recent class"):
    roster = load_roster(course_id)
    events = load_events_for_window(course_id, start, end)

    class_seconds = max(1, int((end - start).total_seconds()))
    student_map = {s["id"]: {"id": s["id"], "name": s.get("name")} for s in roster}

    for ev in events:
        sid = ev.get("student_id")
        if sid and sid not in student_map:
            student_map[sid] = {"id": sid, "name": sid}

    per = defaultdict(lambda: {"yawn":0,"idle_s":0,"tab_away_s":0,"left_frame":0})
    for ev in events:
        sid = ev.get("student_id"); typ = ev.get("type")
        if not sid: continue
        if typ == "yawn": per[sid]["yawn"] += 1
        elif typ == "idle": per[sid]["idle_s"] += int(ev.get("duration_s") or 0)
        elif typ == "tab_away": per[sid]["tab_away_s"] += int(ev.get("duration_s") or 0)
        elif typ == "left_frame": per[sid]["left_frame"] += 1

    out = []
    for sid, info in student_map.items():
        beh = per.get(sid, {"yawn":0,"idle_s":0,"tab_away_s":0,"left_frame":0})
        engaged = class_seconds - beh["idle_s"] - beh["tab_away_s"]
        engaged = max(0, min(class_seconds, engaged))
        engagement_recent = 100.0 * engaged / class_seconds
        engagement_avg = engagement_recent   # TODO: replace with historical mean
        attendance_pct = max(0.0, min(100.0, engagement_recent))  # TODO: replace with your attendance rule

        out.append({
            "id": sid, "name": info.get("name"),
            "engagement_recent": round(engagement_recent, 1),
            "behaviour": beh,
            "engagement_avg_all_classes": round(engagement_avg, 1),
            "attendance_pct": round(attendance_pct, 1)
        })

    return {
        "course_id": course_id,
        "window_label": window_label,
        "class_start": start.astimezone(timezone.utc).isoformat(),
        "class_end": end.astimezone(timezone.utc).isoformat(),
        "last_synced": datetime.now(timezone.utc).isoformat(),
        "students": out
    }
