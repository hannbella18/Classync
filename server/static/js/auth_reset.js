(() => {
  const SUPABASE_URL = window.CLASSYNC_SUPABASE_URL;
  const SUPABASE_ANON_KEY = window.CLASSYNC_SUPABASE_ANON_KEY;

  const form = document.getElementById("resetForm");
  const pwEl = document.getElementById("pw");
  const cfEl = document.getElementById("cf");

  const showAlert = (msg, type = "error") => {
    let box = document.querySelector(".alert");
    if (!box) {
      box = document.createElement("div");
      box.className = "alert";
      form.parentElement.insertBefore(box, form);
    }
    box.className = `alert alert-${type}`;
    box.textContent = msg;
  };

  if (!form || !pwEl || !cfEl) {
    console.error("[Reset] Missing form elements.");
    return;
  }

  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
    showAlert("Supabase keys missing. Check your environment variables.", "error");
    return;
  }

  const supabase = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

  // Establish session from reset link
  (async () => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");

    // PKCE flow
    if (code) {
      const { error } = await supabase.auth.exchangeCodeForSession(code);
      if (error) showAlert("Reset link is invalid or expired. Please request again.", "error");
      return;
    }

    // Implicit flow
    const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : "";
    const hs = new URLSearchParams(hash);
    const access_token = hs.get("access_token");
    const refresh_token = hs.get("refresh_token");

    if (access_token && refresh_token) {
      const { error } = await supabase.auth.setSession({ access_token, refresh_token });
      if (error) showAlert("Reset link is invalid or expired. Please request again.", "error");
    }
  })();

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const pw = (pwEl.value || "").trim();
    const cf = (cfEl.value || "").trim();

    if (!pw || !cf) return showAlert("Please fill in both password fields.", "error");
    if (pw !== cf) return showAlert("Passwords do not match.", "error");
    if (pw.length < 8) return showAlert("Use at least 8 characters.", "error");

    const { error } = await supabase.auth.updateUser({ password: pw });

    if (error) {
      showAlert(error.message || "Failed to update password.", "error");
      return;
    }

    showAlert("Password updated! Redirecting to login...", "success");
    setTimeout(() => (window.location.href = "/login"), 1200);
  });
})();
