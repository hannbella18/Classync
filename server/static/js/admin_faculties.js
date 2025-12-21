// static/js/admin_faculties.js

document.addEventListener("DOMContentLoaded", () => {
  // ===== Slide-down Add Faculty form =====
  const addWrapper = document.getElementById("addFacultyWrapper");
  const toggleBtn = document.getElementById("toggleAddFaculty");
  const closeBtn = document.getElementById("closeAddFaculty");
  const cancelBtn = document.getElementById("cancelAddFaculty");

  const form = document.getElementById("addFacultyForm");
  const formTitle = document.querySelector(".add-fac-header h2");
  const saveBtn = form ? form.querySelector("button[type='submit']") : null;

  const isEditInput = document.getElementById("is_edit_faculty");
  const editIdInput = document.getElementById("edit_faculty_id");

  const nameInput = document.getElementById("fac_name");
  const codeInput = document.getElementById("fac_code");

  function openForm() {
    if (addWrapper) addWrapper.classList.add("open");
  }

  function closeForm() {
    if (addWrapper) addWrapper.classList.remove("open");
    setAddMode();
  }

  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      setAddMode();
      openForm();
    });
  }
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
    if (formTitle) formTitle.textContent = "Add new faculty";
    if (saveBtn) saveBtn.textContent = "Save faculty";

    if (isEditInput) isEditInput.value = "no";
    if (editIdInput) editIdInput.value = "";

    if (nameInput) nameInput.value = "";
    if (codeInput) codeInput.value = "";
  }

  function setEditMode(fac) {
    if (!form) return;

    if (formTitle) formTitle.textContent = "Edit faculty";
    if (saveBtn) saveBtn.textContent = "Update faculty";

    if (isEditInput) isEditInput.value = "yes";
    if (editIdInput) editIdInput.value = fac.id;

    if (nameInput) nameInput.value = fac.name || "";
    if (codeInput) codeInput.value = fac.code || "";
  }

  // ===== EDIT button =====
  document.querySelectorAll(".fac-edit-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const fac = {
        id: btn.dataset.id,
        name: btn.dataset.name,
        code: btn.dataset.code,
      };

      setEditMode(fac);
      openForm();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });

  // ===== DELETE button =====
  document.querySelectorAll(".fac-delete-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const facId = btn.dataset.id;
      const facName = btn.dataset.name || "this faculty";
      if (!facId) return;

      const ok = window.confirm(
        `Are you sure you want to delete ${facName}? This action cannot be undone.`
      );
      if (!ok) return;

      fetch(`/admin/faculties/${facId}/delete`, {
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
            alert(data.error || "Could not delete faculty.");
          }
        })
        .catch(() => {
          alert("Could not delete faculty.");
        });
    });
  });

  // ===== SEARCH filter =====
  const searchInput = document.getElementById("facSearch");

  function applyFacFilters() {
    const query = (searchInput?.value || "").toLowerCase().trim();

    document
      .querySelectorAll(".faculties-table tbody tr")
      .forEach((row) => {
        if (!row.dataset) return;

        const rowName = (row.dataset.name || "").toLowerCase();
        const rowCode = (row.dataset.code || "").toLowerCase();

        const matchesSearch =
          !query ||
          rowName.includes(query) ||
          rowCode.includes(query);

        row.style.display = matchesSearch ? "" : "none";
      });
  }

  if (searchInput) searchInput.addEventListener("input", applyFacFilters);

  applyFacFilters();
});
