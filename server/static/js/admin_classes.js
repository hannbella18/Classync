// static/js/admin_classes.js

document.addEventListener("DOMContentLoaded", () => {
  const addWrapper = document.getElementById("addClassWrapper");
  const toggleBtn = document.getElementById("toggleAddClass");
  const closeBtn = document.getElementById("closeAddClass");
  const cancelBtn = document.getElementById("cancelAddClass");
  const form = document.getElementById("addClassForm");

  const courseCodeInput = document.getElementById("course_code");
  const courseNameInput = document.getElementById("course_name");
  const groupInput = document.getElementById("group_name");
  const lecturerSelect = document.getElementById("lecturer_id");
  const modeSelect = document.getElementById("mode");
  const deptSelect = document.getElementById("dept_id");
  const linkInput = document.getElementById("platform_link");
  const locationInput = document.getElementById("location");
  const daySelect = document.getElementById("day_of_week");
  const timeStartInput = document.getElementById("time_start");
  const timeEndInput = document.getElementById("time_end");

  const isEditInput = document.getElementById("is_edit");
  const editClassIdInput = document.getElementById("edit_class_id");
  const submitBtn = document.querySelector("#addClassForm .primary-btn");

  const locationWrapper = document.getElementById("location-wrapper");
  const linkWrapper = document.getElementById("link-wrapper");

  const searchInput = document.getElementById("classSearch");
  const modeFilter = document.getElementById("classFilterMode");
  const deptFilter = document.getElementById("classFilterDept");
  const rows = document.querySelectorAll(".classes-table tbody .class-row");

  // ---------- Helpers ----------

  function updateModeFields() {
    const mode = (modeSelect.value || "").toLowerCase();

    if (mode === "physical") {
      locationWrapper.style.display = "block";
      linkWrapper.style.display = "none";
    } else if (mode === "online") {
      locationWrapper.style.display = "none";
      linkWrapper.style.display = "block";
    } else {
      // hybrid
      locationWrapper.style.display = "block";
      linkWrapper.style.display = "block";
    }
  }

  function resetForm() {
    // Reset the whole form fields
    form.reset();

    // Clear hidden edit flags
    isEditInput.value = "";
    editClassIdInput.value = "";

    // Allow editing course code again
    courseCodeInput.readOnly = false;

    // Button text
    submitBtn.textContent = "Save class";

    updateModeFields();
  }

  function openForm() {
    addWrapper.classList.add("open");
  }

  function closeForm() {
    addWrapper.classList.remove("open");
    resetForm();
  }

  function applyClassFilters() {
    const term = (searchInput?.value || "").toLowerCase().trim();
    const modeValue = modeFilter ? modeFilter.value : "all";
    const deptValue = deptFilter ? deptFilter.value : "all";

    rows.forEach((row) => {
      const name = (row.dataset.name || "").toLowerCase();
      const code = (row.dataset.code || "").toLowerCase();
      const group = (row.dataset.group || "").toLowerCase();
      const lecturer = (row.dataset.lecturer || "").toLowerCase();
      const rowMode = row.dataset.mode || "";
      const rowDept = row.dataset.dept || "";

      // text match
      const textMatch =
        !term ||
        name.includes(term) ||
        code.includes(term) ||
        group.includes(term) ||
        lecturer.includes(term);

      // mode match
      const modeMatch =
        modeValue === "all" || rowMode === modeValue;

      // dept match
      const deptMatch =
        deptValue === "all" || rowDept === deptValue;

      const show = textMatch && modeMatch && deptMatch;
      row.style.display = show ? "" : "none";
    });
  }

  if (searchInput) {
    searchInput.addEventListener("input", applyClassFilters);
  }
  if (modeFilter) {
    modeFilter.addEventListener("change", applyClassFilters);
  }
  if (deptFilter) {
    deptFilter.addEventListener("change", applyClassFilters);
  }
  
  // ---------- Open/close actions ----------

  toggleBtn.addEventListener("click", () => {
    resetForm();
    openForm();
  });

  closeBtn.addEventListener("click", closeForm);
  cancelBtn.addEventListener("click", closeForm);

  // ---------- Mode show/hide ----------

  modeSelect.addEventListener("change", updateModeFields);
  updateModeFields(); // initial

  // ---------- Edit buttons ----------

  document.querySelectorAll(".table-btn-edit").forEach((btn) => {
    btn.addEventListener("click", () => {
      resetForm();

      const code = btn.dataset.code;
      const name = btn.dataset.name || "";
      const group = btn.dataset.group || "";
      const lecturerId = btn.dataset.lecturerId || "";
      const mode = btn.dataset.mode || "Online";
      const deptId = btn.dataset.deptId || "";
      const location = btn.dataset.location || "";
      const link = btn.dataset.link || "";
      const day = btn.dataset.day || "";
      const timeStart = (btn.dataset.timeStart || "").slice(0, 5);
      const timeEnd = (btn.dataset.timeEnd || "").slice(0, 5);

      // Fill fields
      courseCodeInput.value = code;
      courseNameInput.value = name;
      groupInput.value = group;
      if (lecturerId) lecturerSelect.value = lecturerId;
      modeSelect.value = mode;
      if (deptId) deptSelect.value = deptId;
      locationInput.value = location;
      linkInput.value = link;
      if (day) daySelect.value = day;
      if (timeStart) timeStartInput.value = timeStart;
      if (timeEnd) timeEndInput.value = timeEnd;

      // Mark as edit mode
      isEditInput.value = "yes";
      editClassIdInput.value = code;
      courseCodeInput.readOnly = true;
      submitBtn.textContent = "Update class";

      updateModeFields();
      openForm();
    });
  });

  // ---------- Delete buttons ----------

  document.querySelectorAll(".table-btn-delete").forEach((btn) => {
    btn.addEventListener("click", () => {
      const code = btn.dataset.id;
      if (!confirm(`Are you sure you want to delete class ${code}? This cannot be undone.`)) {
        return;
      }

      // Simple POST form to delete route
      const f = document.createElement("form");
      f.method = "POST";
      f.action = `/admin/classes/${encodeURIComponent(code)}/delete`;  // Correct URL format
      f.submit();
    });
  });
});
