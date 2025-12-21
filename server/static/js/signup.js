// signup.js – validation only

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("signup-form");
  const pw = document.getElementById("password");
  const pw2 = document.getElementById("confirm_password");

  function validatePassword() {
    const v = pw.value || "";
    let msg = "";

    if (v.length < 8) msg = "Password must be at least 8 characters.";
    else if (v.length > 14) msg = "Password must not exceed 14 characters.";
    else if (!/[A-Z]/.test(v)) msg = "Include at least one uppercase letter.";
    else if (!/[a-z]/.test(v)) msg = "Include at least one lowercase letter.";
    else if (!/[0-9]/.test(v)) msg = "Include at least one number.";
    else if (!/[!@#$%^&*(),.?\":{}|<>_\-]/.test(v)) msg = "Include at least one symbol.";

    pw.setCustomValidity(msg);
    return !msg;
  }

  function validateConfirm() {
    const msg = pw.value === pw2.value ? "" : "Passwords do not match.";
    pw2.setCustomValidity(msg);
    return !msg;
  }

  pw.addEventListener("input", () => {
    validatePassword();
    validateConfirm();
  });

  pw2.addEventListener("input", validateConfirm);

  form.addEventListener("submit", (e) => {
    if (!validatePassword()) {
      e.preventDefault();
      pw.reportValidity();
    } else if (!validateConfirm()) {
      e.preventDefault();
      pw2.reportValidity();
    }
  });

  document.querySelectorAll(".pw-icon").forEach((icon) => {
    const input = document.getElementById(icon.dataset.target);
    const openSrc = icon.dataset.open;
    const closedSrc = icon.dataset.closed;

    icon.addEventListener("click", () => {
      const isHidden = input.type === "password";
      input.type = isHidden ? "text" : "password";
      icon.src = isHidden ? openSrc : closedSrc;
    });
  });
});
