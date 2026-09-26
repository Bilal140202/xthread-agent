/* xthread-agent site — interactions (vanilla, no build step) */
(() => {
  "use strict";

  const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---- theme toggle (persisted) ---- */
  const root = document.documentElement;
  const themeIcon = document.getElementById("themeIcon");
  const stored = localStorage.getItem("xt-theme");
  if (stored) root.dataset.theme = stored;
  const syncIcon = () => {
    themeIcon.textContent = root.dataset.theme === "light" ? "light_mode" : "dark_mode";
  };
  syncIcon();
  document.getElementById("themeToggle").addEventListener("click", () => {
    root.dataset.theme = root.dataset.theme === "light" ? "dark" : "light";
    localStorage.setItem("xt-theme", root.dataset.theme);
    syncIcon();
  });

  /* ---- app bar elevation on scroll ---- */
  const bar = document.getElementById("appBar");
  const onScroll = () => bar.classList.toggle("scrolled", window.scrollY > 8);
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ---- scroll reveal ---- */
  const revealables = document.querySelectorAll(".reveal");
  if (prefersReduced || !("IntersectionObserver" in window)) {
    revealables.forEach(el => el.classList.add("visible"));
  } else {
    const io = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (e.isIntersecting) { e.target.classList.add("visible"); io.unobserve(e.target); }
      });
    }, { threshold: 0.12 });
    revealables.forEach(el => io.observe(el));
  }

  /* ---- copy buttons ---- */
  document.querySelectorAll(".copy-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const text = btn.dataset.copy
        || (btn.dataset.copyTarget && document.getElementById(btn.dataset.copyTarget)?.innerText)
        || "";
      try {
        await navigator.clipboard.writeText(text.trim());
        const icon = btn.querySelector(".material-symbols-rounded");
        if (icon) {
          const old = icon.textContent;
          icon.textContent = "check";
          setTimeout(() => { icon.textContent = old; }, 1400);
        }
      } catch { /* clipboard unavailable — silently ignore */ }
    });
  });

  /* ---- typewriter terminal ----
     Shows the real contract of the tool: a run on the first public tweet
     (ID 20 — Jack's "just setting up my twttr"), then the envelope peek. */
  const term = document.getElementById("term");
  const SCRIPT = [
    { cls: "t-cmd",   html: "<span class='t-prompt'>$</span> python3 xthread-agent.py <span class='t-key'>\"https://x.com/jack/status/20\"</span> --json --quiet", speed: 16 },
    { cls: "t-dim",   html: "[ok ] walker slot 'unrollnow': 5 candidate ids", speed: 8 },
    { cls: "t-dim",   html: "[skip] 21…: not a tweet (media id or unavailable)", speed: 8 },
    { cls: "t-ok",    html: "{", speed: 5 },
    { cls: "t-ok",    html: "&nbsp;&nbsp;<span class='t-key'>\"ok\"</span>: true, <span class='t-key'>\"status\"</span>: \"ok\",", speed: 6 },
    { cls: "t-ok",    html: "&nbsp;&nbsp;<span class='t-key'>\"root_id\"</span>: \"20\",", speed: 6 },
    { cls: "t-ok",    html: "&nbsp;&nbsp;<span class='t-key'>\"tweets\"</span>: 1, <span class='t-key'>\"videos\"</span>: 0, <span class='t-key'>\"photos\"</span>: 0,", speed: 6 },
    { cls: "t-ok",    html: "&nbsp;&nbsp;<span class='t-key'>\"errors\"</span>: 0", speed: 6 },
    { cls: "t-ok",    html: "}", speed: 5 },
    { cls: "t-cmd",   html: "<span class='t-prompt'>$</span> python3 demo.py <span class='t-key'>\"https://x.com/jack/status/20\"</span> --skip-download", speed: 16 },
    { cls: "t-warn",  html: " xthread-agent result — status: OK", speed: 6 },
    { cls: "t-dim",   html: " thread    : 1 post(s) reconstructed (candidates=10, related filtered=9)", speed: 6 },
    { cls: "t-dim",   html: " id        : 20", speed: 6 },
    { cls: "t-dim",   html: " author    : @jack (jack)  [verified]  followers=12282063", speed: 6 },
    { cls: "t-dim",   html: " when      : 2006-03-21T20:50:14Z (UTC)", speed: 6 },
    { cls: "t-dim",   html: " text      : just setting up my twttr", speed: 6 },
    { cls: "t-dim",   html: " metrics   : 310865 likes · 124627 RT · 18058 replies", speed: 6 },
    { cls: "t-ok",    html: " manifest  : thread_manifest.json   <— schema-validated envelope", speed: 6 },
  ];

  function typeLine(line) {
    return new Promise(resolve => {
      const div = document.createElement("div");
      div.className = line.cls;
      term.appendChild(div);
      if (prefersReduced) { div.innerHTML = line.html; return resolve(); }
      // typewriter over the plain-text projection of the HTML line
      const tmp = document.createElement("div");
      tmp.innerHTML = line.html;
      const full = tmp.textContent;
      let i = 0;
      const tick = () => {
        i += Math.max(1, Math.round(full.length / Math.min(full.length, 90)));
        div.textContent = full.slice(0, i);
        if (i < full.length) { setTimeout(tick, line.speed); }
        else { div.innerHTML = line.html; resolve(); }
      };
      tick();
    });
  }

  async function play() {
    for (const line of SCRIPT) {
      await typeLine(line);
      await new Promise(r => setTimeout(r, 140));
    }
    const caret = document.createElement("div");
    caret.innerHTML = "<span class='caret'></span>";
    term.appendChild(caret);
  }

  if (term) {
    if ("IntersectionObserver" in window) {
      const once = new IntersectionObserver(entries => {
        if (entries.some(e => e.isIntersecting)) { once.disconnect(); play(); }
      }, { threshold: 0.3 });
      once.observe(term);
    } else {
      play();
    }
  }
})();
