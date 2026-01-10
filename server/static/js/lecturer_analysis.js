// lecturer_analysis.js
(function () {
  console.log("[Analysis] lecturer_analysis.js loaded ✅");

  const courseSel = document.getElementById("courseSelect");
  const sessionSel = document.getElementById("sessionSelect");
  const btnUpdate = document.getElementById("btnUpdate");
  const btnToggleStudents = document.getElementById("btnToggleStudents");

  const kpiAvgEng = document.getElementById("kpiAvgEng");
  const kpiActive = document.getElementById("kpiActive");
  const kpiDrowsy = document.getElementById("kpiDrowsy");
  const kpiTab = document.getElementById("kpiTab");

  // =========================
  // Graph 1: Attendance Drop-off (REPLACED Engagement Over Time)
  // =========================
  const dropOffCanvas = document.getElementById("chartAttendanceDropOff");
  const dropOffPlaceholder = document.querySelector(
    '.chart-placeholder[data-for="chartAttendanceDropOff"]'
  );

  // =========================
  // Graph 2: Engagement by Student
  // =========================
  const engStudentCanvas = document.getElementById("chartEngagementStudent");
  const engStudentPlaceholder = document.querySelector(
    '.chart-placeholder[data-for="chartEngagementStudent"]'
  );

  // =========================
  // Graph 3: Attention State Breakdown
  // =========================
  const stateCanvas = document.getElementById("chartStateBreakdown");
  const statePlaceholder = document.querySelector(
    '.chart-placeholder[data-for="chartStateBreakdown"]'
  );

  // =========================
  // Graph 4: Engagement Risk Timeline
  // =========================
  const riskTimelineCanvas = document.getElementById("chartRiskTimeline");
  const riskTimelinePlaceholder = document.querySelector(
    '.chart-placeholder[data-for="chartRiskTimeline"]'
  );

  // =========================
  // Graph 5: Daily Performance Trend 
  // =========================
  const trendCanvas = document.getElementById("chartSessionTrend");
  const trendPlaceholder = document.querySelector(
    '.chart-placeholder[data-for="chartSessionTrend"]'
  );

  // =========================
  // Graph 6: Risk Level Breakdown
  // =========================
  const riskCanvas = document.getElementById("chartEngagementSession");
  const riskPlaceholder = document.querySelector(
    '.chart-placeholder[data-for="chartEngagementSession"]'
  );

  // Chart refs
  let chartAttendanceDropOff = null;
  let chartEngagementStudent = null;
  let chartStateBreakdown = null;
  let chartRiskTimeline = null;
  let chartSessionTrend = null;  
  let chartRisk = null;

  let showAllStudents = false;

  // =========================
  // Helpers
  // =========================
  function setLoading(selectEl, text) {
    if (!selectEl) return;
    selectEl.innerHTML = "";
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = text;
    selectEl.appendChild(opt);
  }

  function setKpisLoading() {
    if (kpiAvgEng) kpiAvgEng.textContent = "--%";
    if (kpiActive) kpiActive.textContent = "--";
    if (kpiDrowsy) kpiDrowsy.textContent = "--";
    if (kpiTab) kpiTab.textContent = "--";
  }

  function setKpis(k) {
    if (!k) return;
    if (kpiAvgEng) kpiAvgEng.textContent = `${k.avg_engagement ?? 0}%`;
    if (kpiActive) kpiActive.textContent = `${k.students_active ?? 0}`;
    if (kpiDrowsy) kpiDrowsy.textContent = `${k.drowsy_alerts ?? 0}`;
    if (kpiTab) kpiTab.textContent = `${k.tab_switches ?? 0}`;
  }

  function ensureChartJs(placeholderEl) {
    if (typeof Chart === "undefined") {
      console.warn("[Analysis] Chart.js not loaded");
      if (placeholderEl) {
        placeholderEl.style.display = "block";
        placeholderEl.textContent =
          "Chart.js not loaded. Check the CDN script order in HTML.";
      }
      return false;
    }
    return true;
  }

  // =========================
  // Data loaders
  // =========================
  async function loadCourses() {
    if (!courseSel) return;
    setLoading(courseSel, "Loading courses...");

    const res = await fetch("/api/lecturer/courses", { credentials: "include" });
    const data = await res.json();

    courseSel.innerHTML = "";

    const allOpt = document.createElement("option");
    allOpt.value = "";
    allOpt.textContent = "All courses";
    courseSel.appendChild(allOpt);

    if (!data.ok) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "Failed to load courses";
      courseSel.appendChild(opt);
      return;
    }

    data.courses.forEach((c) => {
      const opt = document.createElement("option");
      opt.value = c.course_id;
      opt.textContent = `${c.course_id} — ${c.course_name || ""}`.trim();
      courseSel.appendChild(opt);
    });
  }

  async function loadSessions(courseId = "") {
    if (!sessionSel) return;
    setLoading(sessionSel, "Loading sessions...");

    const url = courseId
      ? `/api/lecturer/sessions?course_id=${encodeURIComponent(courseId)}`
      : `/api/lecturer/sessions`;

    const res = await fetch(url, { credentials: "include" });
    const data = await res.json();

    sessionSel.innerHTML = "";

    if (!data.ok) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "Failed to load sessions";
      sessionSel.appendChild(opt);
      return;
    }

    if (!data.sessions || !data.sessions.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "No sessions yet";
      sessionSel.appendChild(opt);
      sessionSel.value = "";
      return;
    }

    data.sessions.forEach((s) => {
      const opt = document.createElement("option");
      opt.value = String(s.id);
      opt.textContent = s.label;
      sessionSel.appendChild(opt);
    });

    sessionSel.value = String(data.default_session_id || data.sessions[0].id);
  }

  async function loadKpis(sessionId) {
    setKpisLoading();
    if (!sessionId) return;

    const res = await fetch(
      `/api/lecturer/analytics/kpis?session_id=${encodeURIComponent(sessionId)}`,
      { credentials: "include" }
    );
    const data = await res.json();

    if (!data.ok) {
      console.warn("[Analysis] KPI error:", data);
      return;
    }
    setKpis(data.kpis);
  }

  async function loadAttendanceDropOff(sessionId) {
    if (!dropOffCanvas) return;

    if (!sessionId) {
      if (dropOffPlaceholder) {
        dropOffPlaceholder.style.display = "block";
        dropOffPlaceholder.textContent = "No session selected.";
      }
      if (chartAttendanceDropOff) {
        chartAttendanceDropOff.destroy();
        chartAttendanceDropOff = null;
      }
      return;
    }

    if (!ensureChartJs(dropOffPlaceholder)) return;

    if (dropOffPlaceholder) {
      dropOffPlaceholder.style.display = "block";
      dropOffPlaceholder.textContent = "Loading chart...";
    }

    const res = await fetch(
      `/api/lecturer/analytics/attendance_timeline?session_id=${encodeURIComponent(sessionId)}`,
      { credentials: "include" }
    );
    const data = await res.json();

    if (!data.ok) {
        if (dropOffPlaceholder) dropOffPlaceholder.textContent = "Failed to load.";
        return;
    }

    const labels = data.labels || [];
    const active = data.active || [];
    const enrolled = data.enrolled || [];

    if (!labels.length) {
       if (dropOffPlaceholder) {
         dropOffPlaceholder.style.display = "block";
         dropOffPlaceholder.textContent = "No data available.";
       }
       if (chartAttendanceDropOff) {
         chartAttendanceDropOff.destroy();
         chartAttendanceDropOff = null;
       }
       return;
    }

    if (dropOffPlaceholder) dropOffPlaceholder.style.display = "none";
    if (chartAttendanceDropOff) chartAttendanceDropOff.destroy();

    // Render Dual Line Chart
    chartAttendanceDropOff = new Chart(dropOffCanvas.getContext("2d"), {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Total Enrolled",
            data: enrolled,
            borderColor: "#94a3b8", // Gray
            borderDash: [5, 5],     // Dotted Line
            pointRadius: 0,
            borderWidth: 2,
            fill: false
          },
          {
            label: "Active on Camera",
            data: active,
            borderColor: "#2563eb", // Blue
            backgroundColor: "rgba(37, 99, 235, 0.1)",
            pointRadius: 2,
            tension: 0.3,
            fill: true
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: {
            beginAtZero: true,
            title: { display: true, text: "Students" },
            suggestedMax: Math.max(...enrolled) + 2
          },
          x: {
            title: { display: true, text: "Time" }
          }
        },
        plugins: {
            legend: { position: 'top' },
            tooltip: {
                mode: 'index',
                intersect: false
            }
        }
      }
    });

    dropOffCanvas.style.opacity = "1";
  }

  async function loadEngagementByStudent(sessionId) {
    if (!engStudentCanvas) return;

    if (!sessionId) {
      if (engStudentPlaceholder) {
        engStudentPlaceholder.style.display = "block";
        engStudentPlaceholder.textContent = "No session selected / no sessions yet.";
      }
      if (chartEngagementStudent) {
        chartEngagementStudent.destroy();
        chartEngagementStudent = null;
      }
      return;
    }

    if (!ensureChartJs(engStudentPlaceholder)) return;

    if (engStudentPlaceholder) {
      engStudentPlaceholder.style.display = "block";
      engStudentPlaceholder.textContent = "Loading chart...";
    }

    const limit = showAllStudents ? 0 : 10;

    const res = await fetch(
      `/api/lecturer/analytics/engagement_by_student?session_id=${encodeURIComponent(
        sessionId
      )}&limit=${limit}`,
      { credentials: "include" }
    );
    const data = await res.json();

    if (!data.ok) {
      console.warn("[Analysis] engagement_by_student error:", data);
      if (engStudentPlaceholder) engStudentPlaceholder.textContent = "Failed to load chart data.";
      return;
    }

    const labels = data.labels || [];
    const values = data.values || [];

    if (!labels.length) {
      if (engStudentPlaceholder) {
        engStudentPlaceholder.style.display = "block";
        engStudentPlaceholder.textContent = "No student summary yet for this session.";
      }
      if (chartEngagementStudent) {
        chartEngagementStudent.destroy();
        chartEngagementStudent = null;
      }
      return;
    }

    if (engStudentPlaceholder) engStudentPlaceholder.style.display = "none";
    if (chartEngagementStudent) chartEngagementStudent.destroy();

    chartEngagementStudent = new Chart(engStudentCanvas.getContext("2d"), {
      type: "bar",
      data: {
        labels,
        datasets: [{ label: "Avg Engagement (%)", data: values }],
      },
      options: {
        indexAxis: showAllStudents ? "y" : "x",
        responsive: true,
        maintainAspectRatio: false,
        scales: showAllStudents
          ? { x: { min: 0, max: 100 } }
          : { y: { min: 0, max: 100 } },
      },
    });

    engStudentCanvas.style.opacity = "1";
  }

  async function loadStateBreakdown(sessionId) {
    if (!stateCanvas) return;

    if (!sessionId) {
      if (statePlaceholder) {
        statePlaceholder.style.display = "block";
        statePlaceholder.textContent = "No session selected / no sessions yet.";
      }
      if (chartStateBreakdown) {
        chartStateBreakdown.destroy();
        chartStateBreakdown = null;
      }
      return;
    }

    if (!ensureChartJs(statePlaceholder)) return;

    if (statePlaceholder) {
      statePlaceholder.style.display = "block";
      statePlaceholder.textContent = "Loading chart...";
    }

    const res = await fetch(
      `/api/lecturer/analytics/state_breakdown?session_id=${encodeURIComponent(sessionId)}`,
      { credentials: "include" }
    );
    const data = await res.json();

    if (!data.ok) {
      console.warn("[Analysis] state_breakdown error:", data);
      if (statePlaceholder) statePlaceholder.textContent = "Failed to load chart data.";
      return;
    }

    const labels = data.labels || [];
    const values = data.values || [];
    const total = values.reduce((a, b) => a + (Number(b) || 0), 0);

    if (!labels.length || total === 0) {
      if (statePlaceholder) {
        statePlaceholder.style.display = "block";
        statePlaceholder.textContent = "No attention state events yet for this session.";
      }
      if (chartStateBreakdown) {
        chartStateBreakdown.destroy();
        chartStateBreakdown = null;
      }
      return;
    }

    if (statePlaceholder) statePlaceholder.style.display = "none";
    if (chartStateBreakdown) chartStateBreakdown.destroy();

    chartStateBreakdown = new Chart(stateCanvas.getContext("2d"), {
      type: "doughnut",
      data: { labels, datasets: [{ label: "Count", data: values }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: "top" } },
      },
    });

    stateCanvas.style.opacity = "1";
  }

  async function loadRiskBreakdown(sessionId) {
    if (!riskCanvas) return;

    if (!sessionId) {
      if (riskPlaceholder) {
        riskPlaceholder.style.display = "block";
        riskPlaceholder.textContent = "No session selected / no sessions yet.";
      }
      if (chartRisk) { chartRisk.destroy(); chartRisk = null; }
      return;
    }

    if (!ensureChartJs(riskPlaceholder)) return;

    if (riskPlaceholder) {
      riskPlaceholder.style.display = "block";
      riskPlaceholder.textContent = "Loading chart...";
    }

    try {
      const url = `/api/lecturer/analytics/risk_level_breakdown?session_id=${encodeURIComponent(sessionId)}`;
      const res = await fetch(url, { credentials: "include" });
      const data = await res.json();

      if (!res.ok || !data.ok) {
        if (riskPlaceholder) {
          riskPlaceholder.textContent =
            (data && data.error) ? `Failed: ${data.error}` : "Failed to load chart.";
        }
        return;
      }

      const labels = data.labels || [];
      const values = data.values || [];

      if (!labels.length || !values.length) {
        if (riskPlaceholder) riskPlaceholder.textContent = "No risk data yet for this session.";
        return;
      }

      if (riskPlaceholder) riskPlaceholder.style.display = "none";
      if (chartRisk) chartRisk.destroy();

      chartRisk = new Chart(riskCanvas.getContext("2d"), {
        type: "doughnut",
        data: { labels, datasets: [{ data: values, backgroundColor: ["#34d399", "#fbbf24", "#f87171"] }] },
        options: { responsive: true, maintainAspectRatio: false },
      });

      riskCanvas.style.opacity = "1";
    } catch (err) {
      console.error("[RiskBreakdown] fetch error:", err);
      if (riskPlaceholder) riskPlaceholder.textContent = "Network error loading chart.";
    }
  }

  async function loadRiskTimeline(sessionId) {
    if (!riskTimelineCanvas) return;

    if (!sessionId) {
      if (riskTimelinePlaceholder) {
        riskTimelinePlaceholder.style.display = "block";
        riskTimelinePlaceholder.textContent = "No session selected / no sessions yet.";
      }
      if (chartRiskTimeline) {
        chartRiskTimeline.destroy();
        chartRiskTimeline = null;
      }
      return;
    }

    if (!ensureChartJs(riskTimelinePlaceholder)) return;

    if (riskTimelinePlaceholder) {
      riskTimelinePlaceholder.style.display = "block";
      riskTimelinePlaceholder.textContent = "Loading chart...";
    }

    const res = await fetch(
      `/api/lecturer/analytics/engagement_over_time?session_id=${encodeURIComponent(
        sessionId
      )}&bucket_s=60`,
      { credentials: "include" }
    );
    const data = await res.json();

    if (!data.ok || !(data.labels || []).length) {
      if (riskTimelinePlaceholder) {
        riskTimelinePlaceholder.style.display = "block";
        riskTimelinePlaceholder.textContent = "No engagement data yet for this session.";
      }
      if (chartRiskTimeline) {
        chartRiskTimeline.destroy();
        chartRiskTimeline = null;
      }
      return;
    }

    const labels = data.labels || [];
    const engagement = (data.values || []).map((v) => Number(v) || 0);
    const riskScore = engagement.map((e) => Number((1 - e).toFixed(3)));

    const T_LOW = 0.30;
    const T_MED = 0.45;

    // Background Colors Plugin
    const riskBandsPlugin = {
      id: "riskBands",
      beforeDraw(chart) {
        const { ctx, chartArea, scales } = chart;
        if (!chartArea) return;

        const y = scales.y;
        const { left, width, top, bottom } = chartArea;

        const yLow = y.getPixelForValue(T_LOW);
        const yMed = y.getPixelForValue(T_MED);

        ctx.save();
        ctx.fillStyle = "rgba(239, 68, 68, 0.08)"; 
        ctx.fillRect(left, top, width, yMed - top);

        ctx.fillStyle = "rgba(245, 158, 11, 0.08)";
        ctx.fillRect(left, yMed, width, yLow - yMed);

        ctx.fillStyle = "rgba(34, 197, 94, 0.08)";
        ctx.fillRect(left, yLow, width, bottom - yLow);
        ctx.restore();
      },
    };

    if (riskTimelinePlaceholder) riskTimelinePlaceholder.style.display = "none";
    if (chartRiskTimeline) chartRiskTimeline.destroy();

    chartRiskTimeline = new Chart(riskTimelineCanvas.getContext("2d"), {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Risk Score",
            data: riskScore,
            borderColor: "#3b82f6",
            backgroundColor: "rgba(59, 130, 246, 0.5)",
            tension: 0.3,
            pointRadius: 3,
            borderWidth: 2,
            fill: false,
            order: 1
          },
          // Dummy Datasets for LEGEND (Long Rectangles)
          {
            label: "High Risk (> 0.45)",
            data: [],
            backgroundColor: "rgba(239, 68, 68, 0.6)",
            borderColor: "rgba(239, 68, 68, 0.6)",
            borderWidth: 1
          },
          {
            label: "Medium",
            data: [],
            backgroundColor: "rgba(245, 158, 11, 0.6)",
            borderColor: "rgba(245, 158, 11, 0.6)",
            borderWidth: 1
          },
          {
            label: "Low Risk (<= 0.30)",
            data: [],
            backgroundColor: "rgba(34, 197, 94, 0.6)",
            borderColor: "rgba(34, 197, 94, 0.6)",
            borderWidth: 1
          }
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: {
            min: 0,
            max: 1,
            title: { display: true, text: "Risk (0.0 - 1.0)" },
          },
        },
        plugins: {
          legend: { 
            display: true,
            position: 'top',
            align: 'center',       // ✅ CENTERED
            labels: {
                usePointStyle: false, // ✅ FALSE = Box/Rectangle (not circle)
                boxWidth: 40,         // ✅ 40px = Long Rectangle (like above graph)
                font: { size: 11 }
            }
          },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                if (ctx.dataset.data.length === 0) return null;
                const v = ctx.parsed.y;
                let lvl = "Low";
                if (v > T_MED) lvl = "High";
                else if (v > T_LOW) lvl = "Medium";
                return `Risk: ${v.toFixed(2)} (${lvl})`;
              },
            },
          },
        },
      },
      plugins: [riskBandsPlugin],
    });

    riskTimelineCanvas.style.opacity = "1";
  }

  // =========================
  // NEW: Daily Performance Trend
  // =========================
  async function loadSessionTrend(sessionId) {
    if (!trendCanvas) return;

    if (!sessionId) {
      if (trendPlaceholder) {
        trendPlaceholder.style.display = "block";
        trendPlaceholder.textContent = "No session selected / no sessions yet.";
      }
      if (chartSessionTrend) {
        chartSessionTrend.destroy();
        chartSessionTrend = null;
      }
      return;
    }

    if (!ensureChartJs(trendPlaceholder)) return;

    if (trendPlaceholder) {
      trendPlaceholder.style.display = "block";
      trendPlaceholder.textContent = "Loading chart...";
    }

    // Call the API
    const res = await fetch(
      `/api/lecturer/analytics/session_trend?session_id=${encodeURIComponent(sessionId)}`,
      { credentials: "include" }
    );
    const data = await res.json();

    if (!data.ok) {
      console.warn("[Analysis] session_trend error:", data);
      if (trendPlaceholder) trendPlaceholder.textContent = "Failed to load chart data.";
      return;
    }

    const labels = data.labels || [];
    const values = data.values || [];
    const colors = data.colors || [];

    if (!labels.length) {
      if (trendPlaceholder) {
        trendPlaceholder.style.display = "block";
        trendPlaceholder.textContent = "No past data available.";
      }
      if (chartSessionTrend) {
        chartSessionTrend.destroy();
        chartSessionTrend = null;
      }
      return;
    }

    if (trendPlaceholder) trendPlaceholder.style.display = "none";
    if (chartSessionTrend) chartSessionTrend.destroy();

    // Render Vertical Bar Chart
    chartSessionTrend = new Chart(trendCanvas.getContext("2d"), {
      type: "bar",
      data: {
        labels: labels,
        datasets: [{
            label: "Daily Avg Score",
            data: values,
            backgroundColor: colors, // Colors come from backend (Green/Yellow/Red)
            borderRadius: 6,
            barPercentage: 0.6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          // ✅ ADDED LEGEND HERE
          legend: { 
            display: true,
            position: 'top',
            align: 'center',       // Center alignment
            labels: {
                usePointStyle: false, // Box shape (Rectangle)
                boxWidth: 40,         // Wide box width
                font: { size: 11 },
                // Manually generate the 3 categories based on app.py logic
                generateLabels: function(chart) {
                    return [
                        { text: "High (>= 75%)", fillStyle: "#34d399", strokeStyle: "#34d399", lineWidth: 0 },
                        { text: "Moderate",      fillStyle: "#fbbf24", strokeStyle: "#fbbf24", lineWidth: 0 },
                        { text: "Low (< 50%)",   fillStyle: "#f87171", strokeStyle: "#f87171", lineWidth: 0 }
                    ];
                }
            },
            // Prevent clicking the legend from hiding the bars (since it's a guide)
            onClick: (e) => e.stopPropagation()
          },
          tooltip: {
            callbacks: {
              label: (ctx) => ` Score: ${ctx.parsed.y}%`
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            max: 100,
            title: { display: true, text: "Engagement (%)" }
          }
        }
      }
    });

    trendCanvas.style.opacity = "1";
  }

  async function refreshAll() {
    const sessionId = sessionSel?.value || "";
    console.log("[Analysis] refreshAll session:", sessionId);

    await loadKpis(sessionId);
    await loadAttendanceDropOff(sessionId);
    await loadEngagementByStudent(sessionId);
    await loadStateBreakdown(sessionId);
    await loadRiskTimeline(sessionId);
    await loadSessionTrend(sessionId); 
    await loadRiskBreakdown(sessionId);
  }

  // =========================
  // Events
  // =========================
  courseSel?.addEventListener("change", async () => {
    await loadSessions(courseSel.value || "");
    await refreshAll();
  });

  btnUpdate?.addEventListener("click", refreshAll);

  btnToggleStudents?.addEventListener("click", async () => {
    showAllStudents = !showAllStudents;
    btnToggleStudents.textContent = showAllStudents ? "Show top 10" : "Show all";
    await loadEngagementByStudent(sessionSel?.value || "");
  });

  // =========================
  // Init
  // =========================
  (async () => {
    await loadCourses();
    await loadSessions("");
    await refreshAll();
  })();
})();
