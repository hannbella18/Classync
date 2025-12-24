// static/js/summary.js

document.addEventListener("DOMContentLoaded", () => {
  // ===== Hero card elements =====
  const heroRoot = document.getElementById("summaryHero");
  const classId = heroRoot ? heroRoot.dataset.classId : null;

  const totalStudentsEl = document.getElementById("statTotalStudents");
  const avgEngagementEl = document.getElementById("statAvgEngagement");
  const attendanceEl = document.getElementById("statAttendance");

  const joinLinkInput = document.getElementById("joinLinkInput");
  const copyJoinLinkBtn = document.getElementById("copyJoinLinkBtn");

  // ===== Controls & table elements =====
  const sessionSelect = document.getElementById("sessionSelect");
  const refreshButtons = document.querySelectorAll(
    "[data-role='summary-refresh'],[data-role='live-refresh']"
  );
  const csvTopBtn = document.getElementById("downloadCsvTop");
  const liveUpdatedLabel = document.getElementById("liveUpdatedLabel");
  const engagementBody = document.getElementById("engagementBody");

  let currentSessionId = null;
  let totalSessionsCount = 0; // ✅ total sessions in this class (from dropdown API)

  const liveRefreshBtn = document.querySelector("[data-role='live-refresh']");
  if (liveRefreshBtn) {
    liveRefreshBtn.addEventListener("click", () => {
      fetchLiveRoster().catch(console.error);
    });
  }

  // ----------------------------------------------------
  // Helper formatting functions
  // ----------------------------------------------------
  function formatRiskLevel(risk) {
    if (!risk) return "—";
    const r = String(risk).toLowerCase();
    if (r === "low") return "On track";
    if (r === "medium") return "Monitor";
    if (r === "high") return "At risk";
    return risk;
  }

  function formatAttendanceStatus(status) {
    if (!status) return "—";
    const s = String(status).toLowerCase();
    if (s === "present") return "Present";
    if (s === "late") return "Late";
    if (s === "absent") return "Absent";
    return status;
  }

  // ----------------------------------------------------
  // Attendance override (Present / Late / Absent)
  // ----------------------------------------------------
  async function overrideAttendance(studentId, newStatus) {
    if (!classId || !currentSessionId) return;

    try {
      const resp = await fetch(
        `/api/summary/${encodeURIComponent(
          classId
        )}/session/${encodeURIComponent(
          currentSessionId
        )}/attendance_override`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({
            student_id: studentId,
            status: newStatus,
          }),
        }
      );

      const data = await resp.json();
      if (!resp.ok || !data.ok) {
        console.error("[summary] override attendance failed:", data);
        return;
      }

      // Reload hero + table so averages + behaviour reflect override
      await loadHeroStats();
      await loadEngagementForSession(currentSessionId);
    } catch (err) {
      console.error("[summary] override attendance error:", err);
    }
  }

  // ----------------------------------------------------
  // Enrollment Edit / Delete
  // ----------------------------------------------------
    async function handleEditEnrollment(row) {
    if (!classId) return;

    const currentName = row.student_name || "";

    // Only edit the name
    const newName = window.prompt("Edit student name:", currentName);
    if (newName === null) return; // cancelled

    try {
      const resp = await fetch(
        `/api/classes/${encodeURIComponent(
          classId
        )}/enrollment/${encodeURIComponent(row.student_id)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({
            display_name: newName,   // 👈 only send display_name
          }),
        }
      );
      const data = await resp.json();
      if (!resp.ok || !data.ok) {
        console.error("[summary] update enrollment failed:", data);
        return;
      }
      await loadEngagementForSession(currentSessionId);
    } catch (err) {
      console.error("[summary] update enrollment error:", err);
    }
  }

  async function handleDeleteEnrollment(row) {
    if (!classId) return;

    const ok = window.confirm(
      `Remove ${row.student_id} from this class?`
    );
    if (!ok) return;

    try {
      const resp = await fetch(
        `/api/classes/${encodeURIComponent(
          classId
        )}/enrollment/${encodeURIComponent(row.student_id)}`,
        {
          method: "DELETE",
          credentials: "include",
        }
      );
      const data = await resp.json();
      if (!resp.ok || !data.ok) {
        console.error("[summary] delete enrollment failed:", data);
        return;
      }

      // Total students changed → update hero + table
      await loadHeroStats();
      await loadEngagementForSession(currentSessionId);
    } catch (err) {
      console.error("[summary] delete enrollment error:", err);
    }
  }

  // ----------------------------------------------------
  // Render rows for Student Engagement table
  // ----------------------------------------------------
  function renderEngagementRows(rows) {
    if (!engagementBody) return;
    engagementBody.innerHTML = "";

    if (!rows || rows.length === 0) {
      const tr = document.createElement("tr");
      tr.className = "summary-empty-row";
      const td = document.createElement("td");
      td.colSpan = 9;
      td.textContent = "No data yet for this session.";
      tr.appendChild(td);
      engagementBody.appendChild(tr);
      return;
    }

    rows.forEach((row, idx) => {
      const tr = document.createElement("tr");

      const makeCell = (text) => {
        const td = document.createElement("td");
        td.textContent = text;
        return td;
      };

      // No.
      tr.appendChild(makeCell(String(idx + 1)));
      // Student ID
      tr.appendChild(makeCell(row.student_id || "—"));
      // Name
      tr.appendChild(makeCell(row.student_name || "—"));

      // Engagement score for this session
      const engText =
        row.engagement_score == null
          ? "—"
          : `${Math.round(row.engagement_score)}%`;
      tr.appendChild(makeCell(engText));

      // Behaviour (from engagement_summary, nicely formatted)
      const behTd = document.createElement("td");
      behTd.className = "behaviour-cell";

      const behaviourHtml =
        row.behaviour || formatRiskLevel(row.risk_level) || "—";

      // row.behaviour may contain "<br>" from backend → use innerHTML
      behTd.innerHTML = behaviourHtml;
      tr.appendChild(behTd);

      // Average engagement (all sessions in this class)
      const avgEngText =
        row.average_engagement == null
          ? "—"
          : `${Math.round(row.average_engagement)}%`;
      tr.appendChild(makeCell(avgEngText));

      // Attendance buttons (Present / Late / Absent)
      // Attendance: current status text + buttons underneath
      const attTd = document.createElement("td");

      // 1) Current status text
      const statusLabel = document.createElement("div");
      statusLabel.className = "att-status-label";
      statusLabel.textContent = formatAttendanceStatus(
        row.attendance_status
      );
      attTd.appendChild(statusLabel);

      // 2) Buttons row
      const btnRow = document.createElement("div");
      btnRow.className = "att-btn-row";

      const statuses = [
        { key: "present", label: "Present" },
        { key: "absent", label: "Absent" },
      ];

      const currStatus = String(row.attendance_status || "").toLowerCase();

      statuses.forEach((st) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `att-btn att-btn-${st.key}`;  
        btn.textContent = st.label;

        if (currStatus === st.key) {
          btn.classList.add("att-btn-active");
        }

        btn.addEventListener("click", () => {
          overrideAttendance(row.student_id, st.key);
        });

        btnRow.appendChild(btn);
      });

      attTd.appendChild(btnRow);
      tr.appendChild(attTd);


      // Average attendance (across ALL sessions)
      let computedAvg = null;

      // ✅ If backend already provides ANY of these fields, we can compute correctly:
      const attended =
        row.attended_sessions ??
        row.present_sessions ??
        row.sessions_attended ??
        row.attendance_count ??
        null;

      if (attended != null && totalSessionsCount > 0) {
        computedAvg = (Number(attended) / totalSessionsCount) * 100;
      }

      const avgAttText =
        computedAvg != null
          ? `${Math.round(computedAvg)}%`
          : (row.average_attendance == null ? "—" : `${Math.round(row.average_attendance)}%`);

      tr.appendChild(makeCell(avgAttText));

      // Actions: Edit + Delete (icon buttons, side by side)
      const actionsTd = document.createElement("td");

      const actionsWrap = document.createElement("div");
      actionsWrap.className = "summary-actions-wrap";

      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "summary-icon-btn summary-icon-btn-edit";
      editBtn.setAttribute("aria-label", "Edit student");
      editBtn.innerHTML = '<img src="/static/img/pen.png" alt="" />';
      editBtn.addEventListener("click", () => handleEditEnrollment(row));

      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "summary-icon-btn summary-icon-btn-delete";
      delBtn.setAttribute("aria-label", "Remove student");
      delBtn.innerHTML = '<img src="/static/img/bin.png" alt="" />';
      delBtn.addEventListener("click", () => handleDeleteEnrollment(row));

      actionsWrap.appendChild(editBtn);
      actionsWrap.appendChild(delBtn);

      actionsTd.appendChild(actionsWrap);
      tr.appendChild(actionsTd);

      engagementBody.appendChild(tr);
    });
  }

  function formatTimeAgo(isoString) {
    if (!isoString) return "-";
    const ts = new Date(isoString);
    if (Number.isNaN(ts.getTime())) return isoString;

    const diffMs = Date.now() - ts.getTime();
    const diffSec = Math.round(diffMs / 1000);

    if (diffSec < 10) return "just now";
    if (diffSec < 60) return `${diffSec}s ago`;

    const diffMin = Math.round(diffSec / 60);
    if (diffMin < 60) return `${diffMin} min ago`;

    const diffHr = Math.round(diffMin / 60);
    return `${diffHr} hr ago`;
  }

  function renderStatusPill(statusRaw) {
    const s = (statusRaw || "").toLowerCase();
    let label = "Present";
    let cls = "live-status-pill live-status-default";

    if (s === "awake") {
      label = "Awake";
      cls = "live-status-pill live-status-awake";
    } else if (s === "drowsy") {
      label = "Drowsy";
      cls = "live-status-pill live-status-drowsy";
    } else if (s === "away" || s === "tab_away") {
      label = "Away";
      cls = "live-status-pill live-status-away";
    }

    return `
      <span class="${cls}">
        <span class="live-status-dot"></span>
        <span>${label}</span>
      </span>
    `;
  }

  function renderLiveTable(students) {
    const tbody = document.getElementById("liveBody");
    if (!tbody) return;

    tbody.innerHTML = "";

    if (!students || students.length === 0) {
      const tr = document.createElement("tr");
      tr.className = "summary-empty-row";
      const td = document.createElement("td");
      td.colSpan = 5;

      // if backend says no active session, show clearer message
      if (window._liveSessionId === null) {
        td.textContent = "No live session right now. Live roster is only available during ongoing classes.";
      } else {
        td.textContent = "No students yet";
      }

      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }

    students.forEach((st, idx) => {
      const tr = document.createElement("tr");

      tr.innerHTML = `
        <td>${idx + 1}</td>
        <td>${st.student_id || "-"}</td>
        <td>${st.name || "-"}</td>
        <td>${renderStatusPill(st.status)}</td>
        <td>${formatTimeAgo(st.last_seen)}</td>
      `;

      tbody.appendChild(tr);
    });
  }

  async function fetchLiveRoster() {
    const labelEl = document.getElementById("liveUpdatedLabel");
    try {
      // we can pass session_id later if you want it tied to dropdown
      const resp = await fetch("/api/live");
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      if (!data.ok) throw new Error(data.error || "live error");
      
      window._liveSessionId = data.session_id;
      renderLiveTable(data.students || []);

      if (labelEl) {
        labelEl.textContent = "updated just now";
      }
    } catch (err) {
      console.error("Live roster error:", err);
      if (labelEl) {
        labelEl.textContent = "error loading";
      }
    }
  }

  // ----------------------------------------------------
  // Hero cards: fetch data from backend
  // ----------------------------------------------------
  async function loadHeroStats() {
    if (!classId) {
      console.warn("[summary] No classId found on #summaryHero");
      return;
    }

    try {
      const resp = await fetch(
        `/api/summary/${encodeURIComponent(classId)}/hero`,
        { credentials: "include" }
      );

      if (!resp.ok) {
        console.error("[summary] Hero stats HTTP error:", resp.status);
        return;
      }

      const data = await resp.json();
      if (!data.ok) {
        console.error("[summary] Hero stats error payload:", data.error);
        return;
      }

      if (totalStudentsEl) {
        totalStudentsEl.textContent = data.total_students ?? 0;
      }

      if (avgEngagementEl) {
        const val = data.avg_engagement ?? 0;
        avgEngagementEl.textContent = `${Math.round(val)}%`;
      }

      if (attendanceEl) {
        let att = data.current_session_attendance;
        if (att == null) {
          att = data.attendance_14w;
        }
        attendanceEl.textContent =
          att == null ? "--%" : `${Math.round(att)}%`;
      }
    } catch (err) {
      console.error("[summary] Failed to load hero stats:", err);
    }
  }

  // ----------------------------------------------------
  // Sessions dropdown + engagement table
  // ----------------------------------------------------
  async function loadSessionsAndInitialEngagement() {
    if (!classId || !sessionSelect) return;

    try {
      const resp = await fetch(
        `/api/summary/${encodeURIComponent(classId)}/sessions`,
        { credentials: "include" }
      );

      if (!resp.ok) {
        console.error(
          "[summary] sessions HTTP error:",
          resp.status,
          resp.statusText
        );
        return;
      }

      const data = await resp.json();
      if (!data.ok) {
        console.error("[summary] sessions error payload:", data.error);
        return;
      }

      const sessions = data.sessions || [];
      sessionSelect.innerHTML = "";
      totalSessionsCount = sessions.length; // ✅ we’ll use this for avg attendance calc

      if (sessions.length === 0) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "No sessions yet";
        sessionSelect.appendChild(opt);
        currentSessionId = null;
        renderEngagementRows([]);
        return;
      }

      sessions.forEach((s) => {
        const opt = document.createElement("option");
        opt.value = s.id;
        opt.textContent = s.label;
        sessionSelect.appendChild(opt);
      });

      const defaultId = data.default_session_id || sessions[0].id;
      currentSessionId = defaultId;
      sessionSelect.value = String(defaultId);

      await loadEngagementForSession(defaultId);
    } catch (err) {
      console.error("[summary] Failed to load sessions:", err);
    }
  }

  async function loadEngagementForSession(sessionId) {
    if (!classId || !sessionId || !engagementBody) return;

    try {
      const resp = await fetch(
        `/api/summary/${encodeURIComponent(
          classId
        )}/session/${encodeURIComponent(sessionId)}/engagement`,
        { credentials: "include" }
      );

      if (!resp.ok) {
        console.error(
          "[summary] engagement HTTP error:",
          resp.status,
          resp.statusText
        );
        return;
      }

      const data = await resp.json();
      if (!data.ok) {
        console.error("[summary] engagement error payload:", data.error);
        return;
      }

      renderEngagementRows(data.rows || []);
    } catch (err) {
      console.error("[summary] Failed to load engagement table:", err);
    }
  }

  // When user changes the selected session
  if (sessionSelect) {
    sessionSelect.addEventListener("change", () => {
      const sid = sessionSelect.value;
      currentSessionId = sid || null;
      if (sid) {
        loadEngagementForSession(sid);
      } else {
        renderEngagementRows([]);
      }
    });
  }

  // ----------------------------------------------------
  // Other UI behaviour
  // ----------------------------------------------------
  // Refresh buttons: reload hero + sessions + table + live roster
  refreshButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      // 1. Recompute hero cards
      loadHeroStats();

      // 2. Reload sessions list & engagement table
      loadSessionsAndInitialEngagement();

      // 3. Refresh live roster panel
      fetchLiveRoster().catch(console.error);
    });
  });

  // Top Download CSV – all sessions for this class
  if (csvTopBtn) {
    csvTopBtn.addEventListener("click", () => {
      if (!classId) return;

      const url = `/api/summary/${encodeURIComponent(
        classId
      )}/engagement_csv`;

      // Trigger browser download
      window.location.href = url;
    });
  }


  // Update "updated Xs ago" text in Live Roster header
  if (liveUpdatedLabel) {
    const start = Date.now();
    setInterval(() => {
      const diffSec = Math.floor((Date.now() - start) / 1000);
      if (diffSec < 60) {
        liveUpdatedLabel.textContent = `updated ${diffSec}s ago`;
      } else {
        const min = Math.floor(diffSec / 60);
        liveUpdatedLabel.textContent = `updated ${min}m ago`;
      }
    }, 15000);
  }

  // ----------------------------------------------------
  // Copy join link button
  // ----------------------------------------------------
  if (joinLinkInput && copyJoinLinkBtn) {
    copyJoinLinkBtn.addEventListener("click", async () => {
      const url = (joinLinkInput.value || "").trim();
      if (!url) return;

      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(url);
        } else {
          // Fallback for older browsers
          joinLinkInput.select();
          document.execCommand("copy");
          joinLinkInput.blur();
        }

        const original = copyJoinLinkBtn.textContent;
        copyJoinLinkBtn.textContent = "Copied!";
        copyJoinLinkBtn.disabled = true;

        setTimeout(() => {
          copyJoinLinkBtn.textContent = original;
          copyJoinLinkBtn.disabled = false;
        }, 1200);
      } catch (err) {
        console.error("[summary] copy join link error:", err);
        alert("Failed to copy link. You can copy it manually:\n" + url);
      }
    });
  }

  // ----------------------------------------------------
  // Initial load
  // ----------------------------------------------------
  loadHeroStats();
  loadSessionsAndInitialEngagement();
  fetchLiveRoster().catch(console.error);
  setInterval(() => {
    fetchLiveRoster().catch(console.error);
  }, 15000);
});
