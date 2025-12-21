// This runs on http://localhost:5001/* pages.
// It listens for the ping from your website and replies.

console.log("[Classync] status_ping_content.js loaded on", window.location.href);

window.addEventListener("message", (event) => {
  // Just check the type. (We remove the event.source check to be safe.)
  if (!event.data || event.data.type !== "CLASSYNC_EXTENSION_PING") return;

  console.log("[Classync] Received PING from page, sending RESPONSE");

  window.postMessage(
    {
      type: "CLASSYNC_EXTENSION_PING_RESPONSE",
      ok: true, // later you can make this more detailed if you want
    },
    "*"
  );
});
