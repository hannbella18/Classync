document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("join-form");
  if (!form) return;

  const nameInput = document.getElementById("student-name");
  const emailInput = document.getElementById("student-email");
  const errorBox = document.getElementById("join-error");
  const successBox = document.getElementById("join-success");
  const statusText = document.getElementById("join-detect-status");
  const video = document.getElementById("join-video");

  const classId = form.dataset.classId;
  const token = form.dataset.token || "";

  let recognizedStudentId = null;
  let detectInterval = null;
  let stream = null;

  function showError(msg) {
    if (errorBox) {
      errorBox.textContent = msg || "Something went wrong.";
      errorBox.style.display = "block";
    }
    if (successBox) successBox.style.display = "none";
  }

  function showSuccess(msg) {
    if (successBox) {
      successBox.textContent = msg || "Joined successfully.";
      successBox.style.display = "block";
    }
    if (errorBox) errorBox.style.display = "none";
  }

  function setStatus(msg) {
    if (statusText) statusText.textContent = msg;
  }

  /**
   * Fetches the detailed profile (email) for a recognized ID and locks the form.
   */
  async function fetchProfileAndLockForm(studentId) {
    try {
      const url = `/api/student_profile?student_id=${encodeURIComponent(studentId)}&class_id=${encodeURIComponent(classId)}`;
      const res = await fetch(url);
      if (!res.ok) return;

      const data = await res.json().catch(() => null);
      if (!data || !data.ok) return;

      // Fill values if they exist in the DB
      if (data.display_name) nameInput.value = data.display_name;
      if (data.email) emailInput.value = data.email;

      // Lock fields only if the student actually exists in the DB
      if (data.exists) {
        nameInput.readOnly = true;
        emailInput.readOnly = true;
        nameInput.classList.add("join-input-locked");
        emailInput.classList.add("join-input-locked");
      }
    } catch (err) {
      console.error("[join] fetchProfile error:", err);
    }
  }

  async function startCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus("Camera not supported in this browser. You can still join using the form.");
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      video.srcObject = stream;
      await video.play();
      setStatus("Detecting your face… Please look directly at the camera.");
      startDetectLoop();
    } catch (err) {
      console.error("[join] getUserMedia error:", err);
      setStatus("Camera access was denied. You can still join using the form.");
    }
  }

  function stopDetectLoop() {
    if (detectInterval) {
      clearInterval(detectInterval);
      detectInterval = null;
    }
  }

  function stopCamera() {
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
    }
  }

  function startDetectLoop() {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");

    detectInterval = setInterval(async () => {
      if (!video || video.readyState < 2) return;

      const w = video.videoWidth;
      const h = video.videoHeight;
      if (!w || !h) return;

      canvas.width = w;
      canvas.height = h;
      ctx.drawImage(video, 0, 0, w, h);

      const blob = await new Promise((resolve) => canvas.toBlob((b) => resolve(b), "image/jpeg", 0.8));
      if (!blob) return;

      const formData = new FormData();
      formData.append("frame", blob, "frame.jpg");
      formData.append("camera_id", "JOIN_PAGE_" + classId);

      try {
        const res = await fetch("/api/identify", { method: "POST", body: formData });
        const data = await res.json().catch(() => null);
        if (!data || !data.ok || recognizedStudentId) return;

        // --- Logic for Face Identification ---
        if (!data.pending && data.student_id) {
          if (data.student_id === "NEW_FACE") {
            // 1) New face detected: Let them type
            recognizedStudentId = null; 
            setStatus("New face detected! Please enter your details below to enroll.");
            nameInput.readOnly = false;
            emailInput.readOnly = false;
            nameInput.classList.remove("join-input-locked");
            emailInput.classList.remove("join-input-locked");
          } else {
            // 2) Known face recognized: Lock the form
            recognizedStudentId = data.student_id;
            setStatus("Welcome back! We recognised you.");
            
            if (data.name) nameInput.value = data.name;
            await fetchProfileAndLockForm(data.student_id);
          }
          stopDetectLoop();
          return;
        }

        // --- Logic for Detection Feedback ---
        if (!data.student_id && !data.pending && !data.bbox) {
          setStatus("No face detected. Please look at the camera.");
        } else if (data.pending && data.bbox) {
          setStatus("Face detected, calibrating… Please hold still for a moment.");
        } else {
          setStatus("We couldn't clearly recognise you yet. You can still join using the form.");
        }
      } catch (err) {
        console.error("[join] identify error:", err);
      }
    }, 1500);
  }

  startCamera();

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = (nameInput.value || "").trim();
    const email = (emailInput.value || "").trim().toLowerCase();

    if (!name || !email) {
      showError("Please fill in your name and email.");
      return;
    }

    try {
      const res = await fetch(`/api/join/${encodeURIComponent(classId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          email,
          token,
          student_id: recognizedStudentId || null,
        }),
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        showError(data.error || "Unable to join class. Please try again.");
        return;
      }

      showSuccess("You have joined this class. Redirecting to the meeting…");
      const redirectUrl = data.redirect_url;
      if (redirectUrl) {
        setTimeout(() => { window.location.href = redirectUrl; }, 800);
      }
    } catch (err) {
      console.error("[join] submit error:", err);
      showError("Network error. Please try again.");
    } finally {
      stopDetectLoop();
      stopCamera();
    }
  });
});