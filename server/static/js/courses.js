// static/js/courses.js

document.addEventListener("DOMContentLoaded", () => {
  const searchInput = document.getElementById("courseSearch");
  const grid = document.getElementById("coursesGrid");
  const list = document.getElementById("coursesList");
  const viewButtons = document.querySelectorAll(".view-btn");

  // ----- VIEW TOGGLE -----
  viewButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      viewButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      const view = btn.dataset.view;
      if (view === "card") {
        grid.classList.remove("d-none");
        list.classList.add("d-none");
      } else {
        grid.classList.add("d-none");
        list.classList.remove("d-none");
      }
    });
  });

  // ----- SIMPLE SEARCH (only for cards now) -----
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      const term = searchInput.value.toLowerCase().trim();
      const cards = grid.querySelectorAll(".course-card");

      cards.forEach((card) => {
        const name = card.dataset.name || "";
        const code = card.dataset.code || "";
        const match =
          name.includes(term) ||
          code.toLowerCase().includes(term);

        card.style.display = match ? "" : "none";
      });
    });
  }
});
