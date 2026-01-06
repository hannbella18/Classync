(() => {
  const form = document.getElementById("forgotForm");
  if (!form) return;

  const btn = form.querySelector("button[type='submit']");
  form.addEventListener("submit", () => {
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = "Sending...";
  });
})();
