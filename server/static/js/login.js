/* --- PARALLAX EFFECT ON ILLUSTRATION --- */
document.addEventListener("mousemove", (e) => {
    const illust = document.getElementById("parallax");
    if (!illust) return;

    let x = (window.innerWidth / 2 - e.pageX) / 60;
    let y = (window.innerHeight / 2 - e.pageY) / 60;

    illust.style.transform =
        `translate(-50%, -50%) translate(${x}px, ${y}px)`;
});

/* --- PARTICLES BACKGROUND --- */
const particles = document.getElementById("particles");

for (let i = 0; i < 35; i++) {
    let dot = document.createElement("div");
    dot.className = "particle";
    dot.style.left = Math.random() * 100 + "vw";
    dot.style.top = Math.random() * 100 + "vh";
    dot.style.animationDuration = 3 + Math.random() * 4 + "s";
    particles.appendChild(dot);
}

document.addEventListener("DOMContentLoaded", () => {
  const icon = document.querySelector(".login-pw-icon");
  if (!icon) return;

  const input = document.getElementById(icon.dataset.target);
  if (!input) return;

  const openSrc = icon.dataset.open;
  const closedSrc = icon.dataset.closed;

  icon.addEventListener("click", () => {
    const isHidden = input.type === "password";
    input.type = isHidden ? "text" : "password";
    icon.src = isHidden ? openSrc : closedSrc;
  });
});
