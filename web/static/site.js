// The public pages' shared behaviour: the logo, the header (shadow on scroll, menu on phones),
// and demo clips that play muted on loop only while on screen. Needs answer.js (ANCHOR_SVG).
document.querySelectorAll(".logo").forEach(el => el.outerHTML = ANCHOR_SVG);
const nav = document.getElementById("nav");
addEventListener("scroll", () => nav.classList.toggle("scrolled", scrollY > 10), {passive: true});
const menu = document.getElementById("menu-btn"), links = document.getElementById("links");
menu.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>Menu`;
menu.onclick = () => { const open = links.classList.toggle("open"); menu.setAttribute("aria-expanded", String(open)); };
document.addEventListener("click", e => { if (!e.target.closest("#nav")) { links.classList.remove("open"); menu.setAttribute("aria-expanded", "false"); } });

const clips = new IntersectionObserver(es => es.forEach(e => { const v = e.target.querySelector("video");
  if (v) e.isIntersecting ? v.play().catch(() => {}) : v.pause(); }), {threshold: .25});
document.querySelectorAll(".media[data-video]").forEach(m => {
  const v = document.createElement("video");
  Object.assign(v, {muted: true, loop: true, playsInline: true, preload: "metadata", src: m.dataset.video});
  v.setAttribute("muted", ""); v.setAttribute("aria-label", m.dataset.label || "Demo of Anchor");
  v.onerror = () => { m.innerHTML = `<div class="missing">Demo clip coming soon</div>`; };
  m.appendChild(v); clips.observe(m);
});
