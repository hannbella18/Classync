// static/js/admin_dashboard.js
// :contentReference[oaicite:0]{index=0}

document.addEventListener("DOMContentLoaded", () => {
  const buttons = document.querySelectorAll(
    "#btn-create-class, #btn-create-user, #btn-manage-departments, #btn-manage-faculties"
  );

  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.getAttribute("data-target");
      if (target) {
        window.location.href = target; // navigate to route
      }
    });
  });
});
