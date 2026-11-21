/* Shared pieces of the DOS app: icons, the logo, charts, number animation, toasts, dialogs and effects. */
"use strict";
(() => {
  const { esc } = DOS;

  /* ---------- icons (simple line icons, 24x24) ---------- */
  const P = {
    home: "M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z", bot: "M12 3v3M7 8h10a3 3 0 0 1 3 3v6a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3v-6a3 3 0 0 1 3-3zM9 13h.01M15 13h.01M9 17h6",
    pulse: "M3 12h4l3-8 4 16 3-8h4", coin: "M12 3a9 9 0 1 0 .01 0zM9 8h6M9 11h6M10.5 8c2.8 0 2.8 6 0 6H9l4.5 3.5", check: "M20 6L9 17l-5-5", factory: "M3 21V10l6 4V10l6 4V6l6 4v11zM7 17h2M12 17h2M17 17h2",
    wrench: "M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z", radio: "M5 12a7 7 0 0 1 14 0M8.5 12a3.5 3.5 0 0 1 7 0M12 12v.01M2 12a10 10 0 0 1 20 0",
    doc: "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6", shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z", layers: "M12 3l9 5-9 5-9-5zM3 13l9 5 9-5M3 17l9 5 9-5",
    sliders: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4", db: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
    git: "M6 3v12M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9a9 9 0 0 1-9 9", play: "M7 4l13 8-13 8z", stop: "M6 6h12v12H6z",
    spark: "M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z", bank: "M3 10l9-6 9 6M5 10v8M9 10v8M15 10v8M19 10v8M3 21h18", truck: "M3 6h11v9H3zM14 9h4l3 3v3h-7M7 18a2 2 0 1 0 0-.01M17 18a2 2 0 1 0 0-.01",
    store: "M4 9l1-5h14l1 5M4 9h16v11H4zM9 20v-6h6v6", cart: "M3 4h2l2 11h11l2-8H6M9 20a1 1 0 1 0 0-.01M17 20a1 1 0 1 0 0-.01", heart: "M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z",
    megaphone: "M3 11v2a1 1 0 0 0 1 1h3l6 4V6L7 10H4a1 1 0 0 0-1 1zM17 8a5 5 0 0 1 0 8", database: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6",
    search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-4.3-4.3", x: "M6 6l12 12M18 6L6 18", menu: "M4 7h16M4 12h16M4 17h16", user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
    out: "M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4M10 17l5-5-5-5M15 12H3", chat: "M4 5h16v11H8l-4 4z", cog: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19 12l2-1-2-4-2 .5-1.5-1.2L15 4h-6l-.5 2.3L7 7.5 5 7 3 11l2 1v0l-2 1 2 4 2-.5 1.5 1.2L9 20h6l.5-2.3 1.5-1.2 2 .5 2-4z",
    rules: "M5 4h14v16H5zM9 8h6M9 12h6M9 16h3", eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z", lock: "M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4",
    flag: "M5 21V4h11l-1 4 1 4H5", bolt: "M13 2L4 14h7l-1 8 9-12h-7z", clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2", alert: "M12 3l10 18H2zM12 10v4M12 17h.01",
    model: "M12 2l3 6 6 1-4.5 4.5 1 6.5L12 17l-5.5 3 1-6.5L3 9l6-1z", tool: "M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z",
    download: "M12 3v12M7 10l5 5 5-5M4 21h16", refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7", arrow: "M5 12h14M13 6l6 6-6 6",
  };
  DOS.icon = (name, cls = "") => `<svg class="ic ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${P[name] || P.spark}"/></svg>`;

  /* ---------- the DigiQuench "Q" logo with its orbiting ring ---------- */
  DOS.logo = (size = 40) => `<svg class="qlogo" width="${size}" height="${size}" viewBox="0 0 40 40" aria-label="DigiQuench">
    <defs><linearGradient id="qg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FFA21A"/><stop offset="1" stop-color="#3F86FF"/></linearGradient></defs>
    <circle cx="18" cy="18" r="10.5" fill="none" stroke="url(#qg)" stroke-width="5"/>
    <g class="ring"><circle cx="20" cy="20" r="18" fill="none" stroke="rgba(255,255,255,.12)" stroke-width="1" stroke-dasharray="3 5"/><circle cx="38" cy="20" r="2" fill="#FFA21A"/></g>
    <circle cx="29.5" cy="29.5" r="4.6" fill="#3F86FF"/></svg>`;

  /* ---------- labels ---------- */
  DOS.lt = (n) => (n ? `<span class="lt L${n}">L${n}</span>` : "");
  const STATUS = { completed: ["ok", "Done"], waiting_approval: ["warn", "Waiting for a person"], running: ["info", "Working"], failed: ["bad", "Failed"],
    stopped: ["bad", "Stopped"], live: ["ok", "Live"], configured: ["info", "Switched on"], available: ["", "Ready to launch"], pending: ["warn", "Waiting"],
    approved: ["ok", "Approved"], rejected: ["bad", "Rejected"], assigned: ["warn", "Assigned"], acknowledged: ["info", "Acknowledged"], in_progress: ["info", "In progress"],
    resolved: ["ok", "Resolved"], cancelled: ["", "Cancelled"], detected: ["bad", "Detected"], diagnosed: ["warn", "Diagnosed"], dispatched: ["info", "Dispatched"], unassigned: ["bad", "Unassigned"],
    running_m: ["ok", "Running"], warning: ["warn", "Warning"], alarm: ["bad", "Alarm"], maintenance: ["info", "Under repair"], repairing: ["info", "Repairing"],
    High: ["bad", "High risk"], Medium: ["warn", "Medium risk"], Low: ["ok", "Low risk"], open: ["bad", "Open"], closed: ["ok", "Closed"] };
  DOS.status = (s) => { const [c, t] = STATUS[s] || ["", DOS.title(s)]; return `<span class="chip dot ${c}">${esc(t)}</span>`; };
  DOS.argText = (v) => {
    if (v == null) return "–";
    if (Array.isArray(v)) return v.map((x) => (typeof x === "object" ? DOS.argText(x) : x)).join(", ");
    if (typeof v === "object") return Object.entries(v).slice(0, 4).map(([k, x]) => `${DOS.title(k)}: ${typeof x === "object" ? "…" : x}`).join(" · ");
    return String(v);
  };
  DOS.simChip = (sim) => (sim ? `<span class="chip warn" title="Scripted model with real tools and rules">Simulated</span>` : `<span class="chip violet" title="Answered by Gemini">Gemini</span>`);
  DOS.DOMAIN = { Fintech: ["bank", "#3F86FF"], Manufacturing: ["factory", "#FFA21A"], Wholesale: ["truck", "#a78bfa"], Retail: ["store", "#34d399"],
    "E-commerce": ["cart", "#f472b6"], Healthcare: ["heart", "#f87171"], "Digital Marketing": ["megaphone", "#fbbf24"], "Data Automation": ["database", "#22d3ee"] };
  DOS.domIcon = (v, size = "") => { const [i, c] = DOS.DOMAIN[v] || ["spark", "#3F86FF"]; return `<span class="ico ${size}" style="--ic:${c}">${DOS.icon(i)}</span>`; };
  DOS.initials = (s) => String(s || "?").replace(/[^A-Za-z ]/g, " ").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "D";

  /* ---------- charts ---------- */
  DOS.spark = (vals, color = "var(--brand)", lim) => {
    if (!vals || vals.length < 2) return `<svg class="spark"></svg>`;
    const lo = Math.min(...vals, lim ?? Infinity), hi = Math.max(...vals, lim ?? -Infinity), span = hi - lo || 1;
    const pts = vals.map((v, i) => [(i / (vals.length - 1)) * 100, 40 - ((v - lo) / span) * 36 - 2]);
    const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    const limY = lim != null ? 40 - ((lim - lo) / span) * 36 - 2 : null;
    return `<svg class="spark" viewBox="0 0 100 42" preserveAspectRatio="none">
      ${limY != null ? `<line x1="0" x2="100" y1="${limY}" y2="${limY}" stroke="rgba(248,113,113,.55)" stroke-dasharray="2 2" stroke-width=".8"/>` : ""}
      <path d="${d} L100 42 L0 42 Z" fill="${color}" opacity=".12"/><path class="l" d="${d}" stroke="${color}" vector-effect="non-scaling-stroke"/></svg>`;
  };
  DOS.bars = (rows) => {
    const max = Math.max(1, ...rows.map((r) => r.runs));
    return `<div class="bars">${rows.map((r, i) => `<span style="--i:${i};height:${Math.max(4, (r.runs / max) * 100)}%" title="${r.runs} runs, ${r.done} done"><b style="height:${r.runs ? (r.done / r.runs) * 100 : 0}%"></b></span>`).join("")}</div>`;
  };
  DOS.ring = (fraction, color = "var(--brand)", size = 120, label = "") => {
    const r = 46, c = 2 * Math.PI * r, off = c * (1 - Math.max(0, Math.min(1, fraction || 0)));
    return `<div style="position:relative;width:${size}px;height:${size}px"><svg class="ring" width="${size}" height="${size}" viewBox="0 0 110 110">
      <circle class="bg" cx="55" cy="55" r="${r}"/><circle class="fg" cx="55" cy="55" r="${r}" stroke="${color}" stroke-dasharray="${c}" stroke-dashoffset="${off}"/></svg>
      <div style="position:absolute;inset:0;display:grid;place-items:center;text-align:center"><div><b style="font:650 24px var(--disp)">${Math.round((fraction || 0) * 100)}%</b><div class="small muted">${esc(label)}</div></div></div></div>`;
  };

  /* ---------- numbers that count up when they appear ---------- */
  DOS.countUp = (root = document) => {
    DOS.qsa("[data-count]", root).forEach((el) => {
      const end = parseFloat(el.dataset.count) || 0, dec = (el.dataset.count.split(".")[1] || "").length, t0 = performance.now(), dur = 600;
      const step = (t) => { const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 3);
        el.textContent = (end * e).toLocaleString("en-IN", { minimumFractionDigits: dec, maximumFractionDigits: dec }); if (p < 1) requestAnimationFrame(step); };
      requestAnimationFrame(step);
    });
  };
  DOS.tile = (k, v, h = "", icon = "spark", color = "var(--brand)", i = 0) =>
    `<div class="tile rise" style="--i:${i};--tc:${color}"><div class="k">${DOS.icon(icon)}${esc(k)}</div><div class="v" data-count="${v ?? 0}">0</div><div class="h">${h}</div></div>`;

  /* ---------- toasts, dialogs, effects ---------- */
  DOS.toast = (msg, kind = "") => {
    const t = document.createElement("div"); t.className = "toast " + kind;
    t.innerHTML = `<span class="ico" style="--ic:${kind === "bad" ? "var(--bad)" : kind === "ok" ? "var(--ok)" : "var(--brand)"};width:26px;height:26px">${DOS.icon(kind === "bad" ? "alert" : kind === "ok" ? "check" : "spark")}</span><div>${esc(msg)}</div>`;
    DOS.$("toasts").appendChild(t);
    setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 300); }, 4200);
  };
  DOS.modal = (html, onOpen) => {
    const sc = document.createElement("div"); sc.className = "scrim"; sc.innerHTML = `<div class="modal" role="dialog" aria-modal="true">${html}</div>`;
    document.body.appendChild(sc);
    const close = () => { sc.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    sc.addEventListener("click", (e) => { if (e.target === sc || e.target.closest("[data-close]")) close(); });
    if (onOpen) onOpen(sc, close);
    const f = DOS.qs("input,textarea,select", sc); if (f) setTimeout(() => f.focus(), 60);
    return close;
  };
  DOS.confirm = (title, text, okLabel = "Confirm", kind = "primary") => new Promise((resolve) => {
    DOS.modal(`<h3>${esc(title)}</h3><p class="muted">${text}</p><div class="acts"><button class="btn" data-close>Cancel</button><button class="btn ${kind}" id="cOk">${esc(okLabel)}</button></div>`,
      (sc, close) => { DOS.qs("#cOk", sc).onclick = () => { close(); resolve(true); }; sc.addEventListener("click", (e) => { if (e.target.closest("[data-close]")) resolve(false); }); });
  });
  DOS.ripple = (e) => {
    const b = e.target.closest(".btn.primary,.btn.glow"); if (!b) return;   // only the main actions
    const r = b.getBoundingClientRect(), s = document.createElement("span"), d = Math.max(r.width, r.height);
    s.className = "ripple"; s.style.cssText = `width:${d}px;height:${d}px;left:${e.clientX - r.left - d / 2}px;top:${e.clientY - r.top - d / 2}px`;
    b.appendChild(s); setTimeout(() => s.remove(), 650);
  };
  DOS.confetti = (x = innerWidth / 2, y = innerHeight / 2, n = 36) => {
    if (!DOS.CELEBRATE || matchMedia("(prefers-reduced-motion: reduce)").matches) return;   // off by default: calm, professional motion
    const colors = ["#FFA21A", "#3F86FF", "#34d399", "#a78bfa", "#f472b6", "#fbbf24"];
    for (let i = 0; i < n; i++) {
      const c = document.createElement("i"); c.className = "confetti";
      const a = Math.random() * Math.PI * 2, dist = 90 + Math.random() * 180;
      c.style.cssText = `left:${x}px;top:${y}px;background:${colors[i % colors.length]};--x:${Math.cos(a) * dist}px;--y:${Math.sin(a) * dist + 120}px;--r:${Math.random() * 720 - 360}deg`;
      document.body.appendChild(c); setTimeout(() => c.remove(), 1200);
    }
  };
  DOS.typewrite = async (el, text, speed = 4) => {
    el.classList.add("typing"); el.textContent = "";
    const fast = matchMedia("(prefers-reduced-motion: reduce)").matches || text.length > 280;
    if (fast) { el.textContent = text; el.classList.remove("typing"); return; }
    for (let i = 0; i < text.length; i += 3) { el.textContent = text.slice(0, i + 3); await DOS.sleep(speed); }
    el.classList.remove("typing");
  };
  DOS.skeleton = (rows = 4) => `<div class="grid">${Array.from({ length: rows }, (_, i) => `<div class="skel" style="height:${i ? 64 : 110}px"></div>`).join("")}</div>`;
  DOS.empty = (icon, title, text = "", action = "") => `<div class="card center rise" style="padding:38px"><span class="ico" style="margin:0 auto 10px;width:48px;height:48px">${DOS.icon(icon)}</span><h3>${esc(title)}</h3><p class="muted" style="margin:6px 0 14px">${text}</p>${action}</div>`;
  DOS.header = (eyebrow, title, sub, actions = "") => `<div class="ph"><div class="grow"><div class="eyebrow">${eyebrow}</div><h1>${title}</h1>${sub ? `<p class="sub">${sub}</p>` : ""}</div><div class="row">${actions}</div></div>`;
})();
