document.addEventListener("DOMContentLoaded", () => {
  const appWrapper = document.querySelector(".app-wrapper");
  const sidebarToggle = document.getElementById("sidebarToggle");
  const notifToggle = document.getElementById("notifToggle");
  const notifPanel = document.getElementById("notifPanel");

  // ---- Sidebar slide (expand / collapse) ----
  if (sidebarToggle) {
    sidebarToggle.addEventListener("click", () => {
      appWrapper.classList.toggle("sidebar-collapsed");
    });
  }

  // ---- Notification popup toggle ----
  if (notifToggle && notifPanel) {
    notifToggle.addEventListener("click", (e) => {
      e.stopPropagation();
      notifPanel.classList.toggle("open");
      const isOpen = notifPanel.classList.contains("open");
      notifPanel.setAttribute("aria-hidden", String(!isOpen));
    });

    document.addEventListener("click", (e) => {
      if (!notifPanel.classList.contains("open")) return;

      const clickInsidePanel = notifPanel.contains(e.target);
      const clickOnButton = notifToggle.contains(e.target);

      if (!clickInsidePanel && !clickOnButton) {
        notifPanel.classList.remove("open");
        notifPanel.setAttribute("aria-hidden", "true");
      }
    });
  }

  // ===============================
  //      REAL CALENDAR + UPCOMING
  // ===============================

  const calendarGrid = document.getElementById("calendarGrid");
  const monthLabel   = document.getElementById("monthLabel");
  const weekdayLabel = document.getElementById("weekdayLabel");
  const currentDateLabel = document.getElementById("currentDateText");
  const todayBtn = document.getElementById("todayButton");

  const upcomingCard  = document.getElementById("upcomingCard");
  const upcomingTag   = document.getElementById("upcomingTag");
  const upcomingTitle = document.getElementById("upcomingClassTitle");
  const upcomingMeta  = document.getElementById("upcomingClassMeta");

  // ==== Schedule data from backend ====
  // scheduleByDay: {"1":[{class_id, class_name, time_start,...}], "3":[...]}
  const scheduleByDay = window.COURSE_SCHEDULE || {};

  function weekdayKeyFromDate(dateObj) {
    const weekday0 = dateObj.getDay();        // 0=Sun..6=Sat
    return weekday0 === 0 ? "7" : String(weekday0); // 1=Mon..7=Sun
  }

  function formatTime12h(timeStr) {
    if (!timeStr) return "";
    const parts = String(timeStr).split(":");
    if (parts.length < 2) return timeStr;
    let h = parseInt(parts[0], 10);
    const m = parts[1];
    let suffix = "AM";
    if (h === 0) { h = 12; suffix = "AM"; }
    else if (h === 12) { suffix = "PM"; }
    else if (h > 12) { h -= 12; suffix = "PM"; }
    return `${String(h).padStart(2, "0")}:${m} ${suffix}`;
  }

  // Dummy schedule (NOT from DB)
  // key: "YYYY-MM-DD"
  const demoSchedule = {
    "2025-03-03": {
      tag: "Lab session",
      title: "CSC4900 – Progress Lab",
      meta: "09:00 AM – 11:00 AM · Google Meet",
    },
    "2025-03-04": {
      tag: "Next class",
      title: "CSC4506 – Database Security",
      meta: "02:00 PM – 04:00 PM · Google Meet",
    },
    "2025-03-07": {
      tag: "Next class",
      title: "CSC4900 – Final Year Project",
      meta: "10:00 AM – 12:00 PM · Google Meet",
    },
    "2025-03-10": {
      tag: "Consultation",
      title: "FYP 1: 1:1 Consultation",
      meta: "03:00 PM – 04:00 PM · Office Hour",
    },
  };

  const monthNames = [
    "January","February","March","April","May","June",
    "July","August","September","October","November","December"
  ];
  const weekdayNames = [
    "Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"
  ];

  // We’ll show the current month
  const today = new Date();
  let currentYear = today.getFullYear();
  let currentMonth = today.getMonth();     // 0–11
  let selectedDate = new Date(today);      // copy

  function formatISO(dateObj) {
    // YYYY-MM-DD
    const y = dateObj.getFullYear();
    const m = String(dateObj.getMonth() + 1).padStart(2, "0");
    const d = String(dateObj.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
  }

  // Returns true if this date has at least one class from scheduleByDay
  function hasClass(dateObj) {
    const key = weekdayKeyFromDate(dateObj);
    const entries = scheduleByDay[key];
    return Array.isArray(entries) && entries.length > 0;
  }

  function updateUpcoming(dateObj) {
    if (!dateObj) return;

    const day         = dateObj.getDate();
    const monthName   = monthNames[dateObj.getMonth()];
    const weekdayIdx  = dateObj.getDay();      // 0=Sun..6=Sat
    const weekdayName = weekdayNames[weekdayIdx];

    // Labels above calendar + "Current date"
    if (currentDateLabel) {
      currentDateLabel.textContent = `Current date: ${day} ${monthName}`;
    }
    if (weekdayLabel) {
      weekdayLabel.textContent = weekdayName;
    }

    if (!upcomingCard || !upcomingTitle || !upcomingMeta || !upcomingTag) return;

    // small animation
    upcomingCard.classList.remove("fade-pop");
    void upcomingCard.offsetWidth;
    upcomingCard.classList.add("fade-pop");

    const dayKey  = weekdayIdx === 0 ? "7" : String(weekdayIdx); // 1=Mon..7=Sun
    const entries = scheduleByDay[dayKey] || [];

    const extraList = document.getElementById("upcomingExtraList");
    if (extraList) {
      extraList.innerHTML = "";
    }

    if (entries.length === 0) {
      // ----- no class on this date -----
      upcomingTag.style.display = "none";
      upcomingTitle.textContent = "No classes scheduled 🎉";
      upcomingMeta.textContent  = "You have no sessions planned for this date.";
      return;
    }

    // ----- there ARE classes today -----
    // sort by start time so we know which one is "next"
    const sorted = [...entries].sort((a, b) =>
      String(a.time_start).localeCompare(String(b.time_start))
    );

    const main = sorted[0];            // Next class
    const others = sorted.slice(1);    // Also today

    // Tag
    upcomingTag.style.display = "inline-flex";
    upcomingTag.textContent =
      others.length > 0 ? "Class today" : "Only class today";

    // Main class title
    const mainLabel = `${main.class_id} – ${main.class_name || ""}`;
    upcomingTitle.textContent = mainLabel;

    // Main class meta
    const mainTime =
      `${formatTime12h(main.time_start)} – ${formatTime12h(main.time_end)}`;

    let mainLocMode = "";
    if (main.delivery_mode === "Google Meet") {
      mainLocMode = "Google Meet";
    } else if (main.location) {
      mainLocMode = main.location;
    } else if (main.delivery_mode) {
      mainLocMode = main.delivery_mode;
    }
    upcomingMeta.textContent = `${mainTime} · ${mainLocMode}`;

    // ----- Also today (same design as main, no box) -----
    if (extraList && others.length > 0) {
      others.forEach((cls) => {
        const item = document.createElement("div");
        item.className = "upcoming-extra-item";

        const title = document.createElement("div");
        title.className = "upcoming-title";
        title.textContent = `${cls.class_id} – ${cls.class_name || ""}`;

        const time = `${formatTime12h(cls.time_start)} – ${formatTime12h(cls.time_end)}`;

        let loc = "";
        if (cls.delivery_mode === "Google Meet") {
          loc = "Google Meet";
        } else if (cls.location) {
          loc = cls.location;
        } else if (cls.delivery_mode) {
          loc = cls.delivery_mode;
        }

        const meta = document.createElement("div");
        meta.className = "upcoming-meta";
        meta.textContent = `${time} · ${loc}`;

        item.appendChild(title);
        item.appendChild(meta);
        extraList.appendChild(item);
      });
    }
  }

  function buildCalendar(year, month) {
    if (!calendarGrid) return;

    calendarGrid.innerHTML = "";

    const headerRow = document.createElement("div");
    headerRow.className = "calendar-header";
    ["Mo","Tu","We","Th","Fr","Sa","Su"].forEach((lbl) => {
      const span = document.createElement("span");
      span.textContent = lbl;
      headerRow.appendChild(span);
    });
    calendarGrid.appendChild(headerRow);

    const firstOfMonth = new Date(year, month, 1);
    const lastOfMonth  = new Date(year, month + 1, 0);
    const daysInMonth  = lastOfMonth.getDate();

    // convert JS weekday (0=Sun) to index where 0=Mon
    let startIndex = firstOfMonth.getDay() - 1;
    if (startIndex < 0) startIndex = 6; // Sunday

    let dayNum = 1;
    // we’ll build up to 6 rows max
    for (let row = 0; row < 6; row++) {
      const rowDiv = document.createElement("div");
      rowDiv.className = "calendar-row";

      for (let col = 0; col < 7; col++) {
        const btn = document.createElement("button");
        btn.className = "day";

        if (row === 0 && col < startIndex) {
          // days before start of month (blank / muted)
          btn.classList.add("muted");
          btn.textContent = "";
          btn.disabled = true;
        } else if (dayNum > daysInMonth) {
          // after end of month
          btn.classList.add("muted");
          btn.textContent = "";
          btn.disabled = true;
        } else {
          btn.textContent = String(dayNum);

          const thisDate = new Date(year, month, dayNum);

          // mark days that have class so CSS can show a dot
          if (hasClass(thisDate)) {
            btn.classList.add("has-class");
          }

          // mark today
          if (
            thisDate.getFullYear() === today.getFullYear() &&
            thisDate.getMonth() === today.getMonth() &&
            thisDate.getDate() === today.getDate()
          ) {
            btn.classList.add("today");
          }

          // selected state
          if (
            thisDate.getFullYear() === selectedDate.getFullYear() &&
            thisDate.getMonth() === selectedDate.getMonth() &&
            thisDate.getDate() === selectedDate.getDate()
          ) {
            btn.classList.add("selected");
          }

          // click handler
          btn.addEventListener("click", () => {
            selectedDate = thisDate;
            // reset selected class
            const allDays = calendarGrid.querySelectorAll(".day");
            allDays.forEach((d) => d.classList.remove("selected"));
            btn.classList.add("selected");
            updateUpcoming(selectedDate);
          });

          dayNum++;
        }

        rowDiv.appendChild(btn);
      }

      calendarGrid.appendChild(rowDiv);

      if (dayNum > daysInMonth) break; // stop early if done
    }

    // update month name
    if (monthLabel) {
      monthLabel.textContent = monthNames[month];
    }
  }

  // Build calendar for current month and auto-select today
  buildCalendar(currentYear, currentMonth);
  updateUpcoming(selectedDate);

  // Today button jumps back to real current date
  if (todayBtn) {
    todayBtn.addEventListener("click", () => {
      currentYear  = today.getFullYear();
      currentMonth = today.getMonth();
      selectedDate = new Date(today);
      buildCalendar(currentYear, currentMonth);
      updateUpcoming(selectedDate);

      todayBtn.style.transform = "scale(0.94)";
      setTimeout(() => (todayBtn.style.transform = "scale(1)"), 120);
    });
  }
    // ===============================
  //   Load "Your Recent Class" table
  // ===============================
  const recentBody = document.getElementById("recentSessionsBody");

  function shortenLink(url) {
    if (!url) return "-";
    if (url.length <= 35) return url;
    return url.slice(0, 32) + "…";
  }

  if (recentBody) {
    fetch("/api/dashboard/recent-sessions")
      .then((res) => res.json())
      .then((data) => {
        if (!data.ok) return;

        recentBody.innerHTML = "";

        data.sessions.forEach((s) => {
          const tr = document.createElement("tr");

          // No.
          const tdIndex = document.createElement("td");
          tdIndex.textContent = s.index + ".";
          tr.appendChild(tdIndex);

          // Meet link
          const tdLink = document.createElement("td");
          if (s.meet_link) {
            const a = document.createElement("a");
            a.href = s.meet_link;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            a.textContent = shortenLink(s.meet_link);
            tdLink.appendChild(a);
          } else {
            tdLink.textContent = "-";
          }
          tr.appendChild(tdLink);

          // Class (use class_id or class_name)
          const tdClass = document.createElement("td");
          tdClass.textContent = s.class_id || s.class_name || "-";
          tr.appendChild(tdClass);

          recentBody.appendChild(tr);
        });
      })
      .catch((err) => {
        console.error("Failed to load recent sessions:", err);
      });
  }

  const notifClearBtn = document.getElementById("notifClearBtn");
  const notifList = document.querySelector(".notif-list");

  if (notifClearBtn && notifList) {
    notifClearBtn.addEventListener("click", () => {
      fetch("/api/notifications/clear", { method: "POST" })
        .then((res) => res.json())
        .then((data) => {
          if (!data.ok) return;
          // Update panel UI
          notifList.innerHTML = "<li>No notifications yet.</li>";
        })
        .catch((err) => {
          console.error("Failed to clear notifications:", err);
        });
    });
  }

  // ---- ALERTS CLEAR BUTTON LOGIC ----
  const alertClearBtn = document.getElementById("alertClearBtn");
  
  if (alertClearBtn) {
    alertClearBtn.addEventListener("click", () => {
      // 1. Confirm with the user
      if (!confirm("Are you sure you want to clear all active alerts?")) return;

      // 2. Call the backend API
      fetch("/api/alerts/clear", { method: "POST" })
        .then((res) => res.json())
        .then((data) => {
          if (!data.ok) return;
          
          // 3. Reload the page to refresh the list
          window.location.reload();
        })
        .catch((err) => {
          console.error("Failed to clear alerts:", err);
        });
    });
  }

});

/* ===== Interactive attendance donut (dummy data) ===== */

const ATTENDANCE_DATA = {
  present: {
    percent: 95,
    label: "Present",
    color: "#22c55e" // green
  },
  absent: {
    percent: 3,
    label: "Absent",
    color: "#ef4444" // red
  },
  late: {
    percent: 2,
    label: "Late",
    color: "#facc15" // yellow
  }
};

// If backend provided real percentages, override the dummy ones
if (window.ATTENDANCE_DATA_FROM_SERVER) {
  const s = window.ATTENDANCE_DATA_FROM_SERVER;
  ["present", "absent", "late"].forEach((key) => {
    const val = s[key];
    if (typeof val === "number" && !Number.isNaN(val)) {
      ATTENDANCE_DATA[key].percent = val;
    }
  });
}

function setupAttendanceChart() {
  const ring   = document.getElementById("attendanceRing");
  const value  = document.getElementById("attendanceValue");
  const label  = document.getElementById("attendanceLabel");
  const legend = document.getElementById("attendanceLegend");

  if (!ring || !value || !label || !legend) return;

  function updateAttendance(type) {
    const data = ATTENDANCE_DATA[type];
    if (!data) return;  // <- if key doesn't exist, do nothing

    ring.style.setProperty("--percent", data.percent);
    ring.style.setProperty("--ring-color", data.color);
    value.textContent = data.percent + "%";
    label.textContent = data.label;

    legend.querySelectorAll(".legend-item").forEach(li => {
      li.classList.toggle("active", li.dataset.type === type);
    });
  }

  legend.addEventListener("click", (e) => {
    const item = e.target.closest(".legend-item");
    if (!item) return;
    updateAttendance(item.dataset.type);
  });

  // initial view
  updateAttendance("present");
}
document.addEventListener("DOMContentLoaded", setupAttendanceChart);


