// Classync – Lecturer Settings (accordion with smooth animation)

document.addEventListener("DOMContentLoaded", () => {
  const cards = document.querySelectorAll("[data-collapsible]");

  function closeCard(card) {
    const header = card.querySelector(".settings-collapsible-header");
    const body = card.querySelector(".settings-collapsible-body");

    card.classList.remove("open");
    card.setAttribute("data-open", "false");
    header.setAttribute("aria-expanded", "false");

    // animate to closed
    body.style.maxHeight = "0px";
  }

  function openCard(card) {
    const header = card.querySelector(".settings-collapsible-header");
    const body = card.querySelector(".settings-collapsible-body");

    // close others (accordion)
    cards.forEach(c => { if (c !== card) closeCard(c); });

    card.classList.add("open");
    card.setAttribute("data-open", "true");
    header.setAttribute("aria-expanded", "true");

    // animate to full height
    body.style.maxHeight = body.scrollHeight + "px";
  }

  // init: start all closed
  cards.forEach(card => {
    const header = card.querySelector(".settings-collapsible-header");
    const body = card.querySelector(".settings-collapsible-body");

    card.classList.remove("open");
    card.setAttribute("data-open", "false");
    header.setAttribute("aria-expanded", "false");

    // IMPORTANT: do NOT use hidden now
    body.hidden = false;
    body.style.maxHeight = "0px";

    header.addEventListener("click", () => {
      const isOpen = card.getAttribute("data-open") === "true";
      if (isOpen) closeCard(card);
      else openCard(card);
    });
  });

  // Optional: keep animation correct on window resize
  window.addEventListener("resize", () => {
    const open = document.querySelector(".settings-collapsible.open .settings-collapsible-body");
    if (open) open.style.maxHeight = open.scrollHeight + "px";
  });

  // Password show/hide (reuse login behavior)
    document.querySelectorAll(".pw-icon").forEach(icon => {
    icon.addEventListener("click", () => {
        const targetId = icon.dataset.target;
        const input = document.getElementById(targetId);
        if (!input) return;

        const openSrc = icon.dataset.open;
        const closedSrc = icon.dataset.closed;

        if (input.type === "password") {
        input.type = "text";
        if (openSrc) icon.src = openSrc;
        } else {
        input.type = "password";
        if (closedSrc) icon.src = closedSrc;
        }
    });
    });
});
