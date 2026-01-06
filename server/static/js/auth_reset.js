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

  if (!form || !pwEl || !cfEl) return;

  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
    showAlert("Supabase keys missing.", "error");
    return;
  }

  const supabase = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

  // --- NEW LOGIC START ---
  // Handle the session verification immediately
  (async () => {
    const params = new URLSearchParams(window.location.search);
    const token_hash = params.get("code"); // We passed .TokenHash as 'code' in the email
    const type = params.get("type") || "recovery";

    // 1. If we have a token_hash (from our new email template)
    if (token_hash) {
      const { error } = await supabase.auth.verifyOtp({
        token_hash,
        type: type,
      });
      
      if (error) {
        showAlert("Reset link is invalid or expired. Please request a new one.", "error");
        console.error("Verify Error:", error);
      } else {
        // Success! The user is now technically "logged in" for this session
        console.log("Session established via Email Token");
      }
      return;
    }

    // 2. Fallback: Check for standard OAuth code (if you didn't change the email template)
    const authCode = params.get("code"); 
    if (authCode && !token_hash) { // Avoid conflict if both named code
       const { error } = await supabase.auth.exchangeCodeForSession(authCode);
       if (error) showAlert("Invalid link.", "error");
       return;
    }

    // 3. Fallback: Check for #access_token (Legacy/Implicit)
    const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : "";
    if (hash.includes("access_token")) {
       const hs = new URLSearchParams(hash);
       const access_token = hs.get("access_token");
       const refresh_token = hs.get("refresh_token");
       if (access_token) {
         await supabase.auth.setSession({ access_token, refresh_token });
       }
    }
  })();
  // --- NEW LOGIC END ---

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const pw = (pwEl.value || "").trim();
    const cf = (cfEl.value || "").trim();

    if (!pw || !cf) return showAlert("Please fill in both password fields.", "error");
    if (pw !== cf) return showAlert("Passwords do not match.", "error");
    if (pw.length < 8) return showAlert("Use at least 8 characters.", "error");

    // Because verifyOtp (above) established the session, we can now simply updateUser
    const { error } = await supabase.auth.updateUser({ password: pw });

    if (error) {
      showAlert(error.message || "Failed to update password.", "error");
      return;
    }

    showAlert("Password updated! Redirecting to login...", "success");
    setTimeout(() => (window.location.href = "/login"), 1500);
  });
})();