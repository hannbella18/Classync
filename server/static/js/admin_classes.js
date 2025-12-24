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
  const modeInput = document.getElementById("mode"); // now readonly input  const deptSelect = document.getElementById("dept_id");
  const linkInput = document.getElementById("platform_link");
  const daySelect = document.getElementById("day_of_week");
  const timeStartInput = document.getElementById("time_start");
  const timeEndInput = document.getElementById("time_end");

  const isEditInput = document.getElementById("is_edit");
  const editClassIdInput = document.getElementById("edit_class_id");
  const submitBtn = document.querySelector("#addClassForm .primary-btn");

  const linkWrapper = document.getElementById("link-wrapper");

  const searchInput = document.getElementById("classSearch");
  const deptFilter = document.getElementById("classFilterDept");
  const rows = document.querySelectorAll(".classes-table tbody .class-row");

  // ---------- Helpers ----------

  function updateModeFields() {
    if (linkWrapper) linkWrapper.style.display = "block";
  }

  function resetForm() {
    // Reset the whole form fields
    form.reset();

    if (modeInput) modeInput.value = "Online";

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
    const deptValue = deptFilter ? deptFilter.value : "all";

    rows.forEach((row) => {
      const name = (row.dataset.name || "").toLowerCase();
      const code = (row.dataset.code || "").toLowerCase();
      const group = (row.dataset.group || "").toLowerCase();
      const lecturer = (row.dataset.lecturer || "").toLowerCase();
      const rowDept = row.dataset.dept || "";

      // text match
      const textMatch =
        !term ||
        name.includes(term) ||
        code.includes(term) ||
        group.includes(term) ||
        lecturer.includes(term);

      // dept match
      const deptMatch =
        deptValue === "all" || rowDept === deptValue;

      const show = textMatch && deptMatch;
      row.style.display = show ? "" : "none";
    });
  }

  if (searchInput) {
    searchInput.addEventListener("input", applyClassFilters);
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
      const link = btn.dataset.link || "";
      const day = btn.dataset.day || "";
      const timeStart = (btn.dataset.timeStart || "").slice(0, 5);
      const timeEnd = (btn.dataset.timeEnd || "").slice(0, 5);

      // Fill fields
      courseCodeInput.value = code;
      courseNameInput.value = name;
      groupInput.value = group;
      if (lecturerId) lecturerSelect.value = lecturerId;
      if (deptId) deptSelect.value = deptId;
      if (modeInput) modeInput.value = "Online";
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
      const code = btn.dataset.id;  // Get class code from data-id
      if (!confirm(`Are you sure you want to delete class ${code}? This cannot be undone.`)) {
        return;
      }

      // Log to check if the code is correct
      console.log("Deleting class:", code);

      // Create the form and append it to the body
      const f = document.createElement("form");
      f.method = "POST";
      f.action = `/admin/classes/${encodeURIComponent(code)}/delete`;  // Correct URL format
      document.body.appendChild(f);

      // Log to confirm the form is being created
      console.log("Form created, submitting...");

      // Submit the form
      setTimeout(() => {
        f.submit();
        console.log("Form submitted");
      }, 0);
    });
  });
});
