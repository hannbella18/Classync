// join_content.js - runs only on /join/<classId> pages
const COURSE_KEY = "classync_course_id";

function parseCourseIdFromJoinUrl(urlStr) {
  try {
    const u = new URL(urlStr);
    const parts = (u.pathname || "").split("/").filter(Boolean);
    const joinIdx = parts.indexOf("join");
    if (joinIdx !== -1 && parts[joinIdx + 1]) {
      return decodeURIComponent(parts[joinIdx + 1]).trim();
    }
  } catch (e) {}
  return null;
}

const cid = parseCourseIdFromJoinUrl(location.href);
if (cid && chrome?.storage?.local) {
  chrome.storage.local.set({ [COURSE_KEY]: cid }, () => {
    console.log("[Classync] Saved course id from join page:", cid);
  });
}
