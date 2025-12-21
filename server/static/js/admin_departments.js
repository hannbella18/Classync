// static/js/admin_departments.js

document.addEventListener("DOMContentLoaded", () => {
  // ===== Slide-down Add Department form =====
  const addWrapper = document.getElementById("addDepartmentWrapper");
  const toggleBtn = document.getElementById("toggleAddDepartment");
  const closeBtn = document.getElementById("closeAddDepartment");
  const cancelBtn = document.getElementById("cancelAddDepartment");

  const form = document.getElementById("addDepartmentForm");
  const formTitle = document.querySelector(".add-dept-header h2");
  const saveBtn = form ? form.querySelector("button[type='submit']") : null;

  const isEditInput = document.getElementById("is_edit_department");
  const editIdInput = document.getElementById("edit_department_id");

  const codeInput = document.getElementById("dept_code");
  const nameInput = document.getElementById("dept_name");
  const facultySelect = document.getElementById("dept_faculty");
  const statusSelect = document.getElementById("dept_status"); // (optional, may not exist)

  function openForm() {
    if (addWrapper) addWrapper.classList.add("open");
  }

  function closeForm() {
    if (addWrapper) addWrapper.classList.remove("open");
    setAddMode();
  }

  if (toggleBtn) toggleBtn.addEventListener("click", () => {
    setAddMode();
    openForm();
  });
  if (closeBtn) closeBtn.addEventListener("click", closeForm);
  if (cancelBtn) {
    cancelBtn.addEventListener("click", (e) => {
      e.preventDefault();
      closeForm();
    });
  }

  // ===== Mode switching (Add / Edit) =====
  function setAddMode() {
    if (!form) return;
    if (formTitle) formTitle.textContent = "Add new department";
    if (saveBtn) saveBtn.textContent = "Save department";

    if (isEditInput) isEditInput.value = "no";
    if (editIdInput) editIdInput.value = "";

    if (codeInput) codeInput.value = "";
    if (nameInput) nameInput.value = "";
    if (facultySelect) facultySelect.value = "";
    if (statusSelect) statusSelect.value = "Active";
  }

  function setEditMode(dept) {
    if (!form) return;

    if (formTitle) formTitle.textContent = "Edit department";
    if (saveBtn) saveBtn.textContent = "Update department";

    if (isEditInput) isEditInput.value = "yes";
    if (editIdInput) editIdInput.value = dept.id;

    if (codeInput) codeInput.value = dept.code || "";
    if (nameInput) nameInput.value = dept.name || "";
    if (facultySelect) facultySelect.value = dept.facultyId || "";
    if (statusSelect) statusSelect.value = dept.status || "Active";
  }

  // ===== EDIT button: open form in edit mode =====
  document.querySelectorAll(".table-btn-edit").forEach((btn) => {
    btn.addEventListener("click", () => {
      const row = btn.closest("tr");

      const dept = {
        id: btn.dataset.id || row?.dataset.id,
        code: btn.dataset.deptId || row?.dataset.deptId,
        name: btn.dataset.name || row?.dataset.name,
        facultyId: btn.dataset.facultyId || row?.dataset.facultyId,
        status: btn.dataset.status || "Active",
      };

      setEditMode(dept);
      openForm();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });

  // ===== DELETE button =====
  document.querySelectorAll(".table-btn-delete").forEach((btn) => {
    btn.addEventListener("click", () => {
      const deptId = btn.dataset.id;
      const deptName = btn.dataset.name || "this department";
      if (!deptId) return;

      const ok = window.confirm(
        `Are you sure you want to delete ${deptName}? This action cannot be undone.`
      );
      if (!ok) return;

      fetch(`/admin/departments/${deptId}/delete`, {
        method: "POST",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
        },
      })
        .then((res) => res.json())
        .then((data) => {
          if (data && data.success) {
            window.location.reload();
          } else {
            alert("Could not delete department.");
          }
        })
        .catch(() => {
          alert("Could not delete department.");
        });
    });
  });

  // ===== SEARCH & FILTER =====
  const searchInput = document.getElementById("deptSearch");
  const facultyFilter = document.getElementById("deptFacultyFilter");

  function applyDeptFilters() {
    const query = (searchInput?.value || "").toLowerCase().trim();
    const filterFaculty = (facultyFilter?.value || "all").toLowerCase();

    document
      .querySelectorAll(".departments-table tbody tr")
      .forEach((row) => {
        if (!row.dataset) return;

        const rowName = (row.dataset.name || "").toLowerCase();
        const rowFacultyId = (row.dataset.facultyId || "").toLowerCase();

        const matchesSearch = !query || rowName.includes(query);
        const matchesFaculty =
          filterFaculty === "all" || rowFacultyId === filterFaculty;

        row.style.display = matchesSearch && matchesFaculty ? "" : "none";
      });
  }

  if (searchInput) searchInput.addEventListener("input", applyDeptFilters);
  if (facultyFilter) facultyFilter.addEventListener("change", applyDeptFilters);

  applyDeptFilters();
});
