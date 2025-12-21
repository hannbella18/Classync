document.addEventListener("DOMContentLoaded", () => {
  // ===== Slide-down Add User form =====
  const addWrapper = document.getElementById("addUserWrapper");
  const toggleBtn = document.getElementById("toggleAddUser");
  const closeBtn = document.getElementById("closeAddUser");
  const cancelBtn = document.getElementById("cancelAddUser");

  const form = document.getElementById("addUserForm");
  const formTitle = document.querySelector(".add-user-header h2");
  const saveBtn = form ? form.querySelector("button[type='submit']") : null;

  const isEditInput = document.getElementById("is_edit");
  const editUserIdInput = document.getElementById("edit_user_id");

  const nameInput = document.getElementById("user_name");
  const emailInput = document.getElementById("user_email");
  const roleSelect = document.getElementById("user_role");
  const deptSelect = document.getElementById("user_department");
  const deptGroup =
    document.getElementById("departmentGroup") ||
    (deptSelect ? deptSelect.closest(".form-group") : null);
  const pwInput = document.getElementById("user_password");

  function openForm() {
    if (addWrapper) addWrapper.classList.add("open");
  }

  function closeForm() {
    if (addWrapper) addWrapper.classList.remove("open");
    setAddMode(); // reset to add when closing
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
    if (formTitle) formTitle.textContent = "Add new user";
    if (saveBtn) saveBtn.textContent = "Save user";

    if (isEditInput) isEditInput.value = "no";
    if (editUserIdInput) editUserIdInput.value = "";

    if (nameInput) nameInput.value = "";
    if (emailInput) emailInput.value = "";
    if (roleSelect) roleSelect.value = "lecturer";
    if (pwInput) pwInput.value = "";
    if (deptSelect) deptSelect.value = "";

    updateDeptVisibility();
  }

  function setEditMode(user) {
    if (!form) return;

    if (formTitle) formTitle.textContent = "Edit user";
    if (saveBtn) saveBtn.textContent = "Update user";

    if (isEditInput) isEditInput.value = "yes";
    if (editUserIdInput) editUserIdInput.value = user.id;

    if (nameInput) nameInput.value = user.name || "";
    if (emailInput) emailInput.value = user.email || "";
    if (roleSelect) roleSelect.value = user.role || "lecturer";
    if (pwInput) pwInput.value = ""; // empty = keep old password

    if (deptSelect && user.deptId) {
      deptSelect.value = user.deptId;
    } else if (deptSelect) {
      deptSelect.value = "";
    }

    updateDeptVisibility();
  }

  // ===== TABLE: show/hide hashed password =====
  // Fill plain text from data-pw attribute
  document.querySelectorAll(".pw-plain").forEach((span) => {
    const pw = span.dataset.pw || "";
    span.textContent = pw;
  });

  document.querySelectorAll(".pw-toggle-table").forEach((btn) => {
    btn.addEventListener("click", () => {
      const cell = btn.closest(".pw-cell");
      if (!cell) return;

      const masked = cell.querySelector(".pw-masked");
      const plain = cell.querySelector(".pw-plain");
      const iconClosed = btn.querySelector(".pw-icon-closed");
      const iconOpen = btn.querySelector(".pw-icon-open");

      const isHidden =
        !plain.style.display || plain.style.display === "none";

      if (isHidden) {
        plain.style.display = "inline";
        masked.style.display = "none";
        if (iconClosed && iconOpen) {
          iconClosed.style.display = "none";
          iconOpen.style.display = "inline";
        }
      } else {
        plain.style.display = "none";
        masked.style.display = "inline";
        if (iconClosed && iconOpen) {
          iconClosed.style.display = "inline";
          iconOpen.style.display = "none";
        }
      }
    });
  });

  // ===== FORM: show/hide temp password input =====
  const formToggleBtn = document.querySelector(".pw-toggle-form");
  if (pwInput && formToggleBtn) {
    const iconClosed = formToggleBtn.querySelector(".pw-icon-closed");
    const iconOpen = formToggleBtn.querySelector(".pw-icon-open");

    formToggleBtn.addEventListener("click", () => {
      const isPassword = pwInput.type === "password";
      if (isPassword) {
        pwInput.type = "text";
        if (iconClosed && iconOpen) {
          iconClosed.style.display = "none";
          iconOpen.style.display = "inline";
        }
      } else {
        pwInput.type = "password";
        if (iconClosed && iconOpen) {
          iconClosed.style.display = "inline";
          iconOpen.style.display = "none";
        }
      }
    });
  }

  // ===== Role vs Department (admin → no department) =====
  function updateDeptVisibility() {
    if (!roleSelect || !deptSelect) return;

    const roleVal = (roleSelect.value || "").toLowerCase();
    if (roleVal === "admin") {
      deptSelect.value = "";
      deptSelect.disabled = true;
      if (deptGroup) deptGroup.classList.add("disabled");
    } else {
      deptSelect.disabled = false;
      if (deptGroup) deptGroup.classList.remove("disabled");
    }
  }

  if (roleSelect) {
    roleSelect.addEventListener("change", updateDeptVisibility);
    updateDeptVisibility();
  }

  // ===== EDIT button: open form in edit mode =====
  document.querySelectorAll(".table-btn-edit").forEach((btn) => {
    btn.addEventListener("click", () => {
      const user = {
        id: btn.dataset.id,
        name: btn.dataset.name,
        email: btn.dataset.email,
        role: (btn.dataset.role || "lecturer").toLowerCase(),
        deptId: btn.dataset.deptId || "",
      };

      setEditMode(user);
      openForm();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });

  // ===== DELETE button: confirm + POST =====
  document.querySelectorAll(".table-btn-delete").forEach((btn) => {
    btn.addEventListener("click", () => {
      const userId = btn.dataset.id;
      const userName = btn.dataset.name || "this user";

      if (!userId) return;

      const ok = window.confirm(
        `Are you sure you want to delete ${userName}? This action cannot be undone.`
      );
      if (!ok) return;

      fetch(`/admin/users/${userId}/delete`, {
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
            alert("Could not delete user.");
          }
        })
        .catch(() => {
          alert("Could not delete user.");
        });
    });
  });

  // ===== SEARCH & FILTER (name/email + role) =====
  const searchInput = document.getElementById("userSearch");
  const listRoleFilter = document.getElementById("userRoleFilter");

  function applyUserFilters() {
    const query = (searchInput?.value || "").toLowerCase().trim();
    const filterRole = (listRoleFilter?.value || "all").toLowerCase();

    document
      .querySelectorAll(".users-table tbody tr")
      .forEach((row) => {
        // Skip the "no users" empty row (it has no data-role)
        if (!row.dataset || !row.dataset.role) return;

        const rowName = (row.dataset.name || "").toLowerCase();
        const rowEmail = (row.dataset.email || "").toLowerCase();
        const rowRole = (row.dataset.role || "").toLowerCase();

        const matchesSearch =
          !query ||
          rowName.includes(query) ||
          rowEmail.includes(query);

        const matchesRole =
          filterRole === "all" || rowRole === filterRole;

        row.style.display = matchesSearch && matchesRole ? "" : "none";
      });
  }

  if (searchInput) {
    searchInput.addEventListener("input", applyUserFilters);
  }
  if (listRoleFilter) {
    listRoleFilter.addEventListener("change", applyUserFilters);
  }

  // initial state
  applyUserFilters();
});
