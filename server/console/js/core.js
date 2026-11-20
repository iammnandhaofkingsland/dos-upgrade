/* DOS app core: state, server requests, live streams, the page router and the menu for each role.
   Every other file adds pages or pieces to the single global object DOS. Nothing here draws a page. */
"use strict";
const DOS = (window.DOS = {
  S: { token: localStorage.getItem("dos_token") || "", me: null, page: "", timers: [], streams: [] },
  pages: {},          // name -> { title, group, render(el, arg) }  (added by the page files)
});

/* ---------- small helpers used everywhere ---------- */
DOS.$ = (id) => document.getElementById(id);
DOS.qs = (sel, el = document) => el.querySelector(sel);
DOS.qsa = (sel, el = document) => [...el.querySelectorAll(sel)];
DOS.esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
DOS.num = (n) => (n == null || isNaN(n) ? "–" : Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 }));
DOS.inr = (n) => (n == null ? "–" : "Rs " + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 }));
DOS.pct = (x) => (x == null ? "–" : Math.round(x * 100) + "%");
DOS.ago = (t) => {
  if (!t) return "–";
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 50) return "just now"; if (s < 3600) return Math.round(s / 60) + " min ago";
  if (s < 86400) return Math.round(s / 3600) + " h ago"; return Math.round(s / 86400) + " d ago";
};
DOS.title = (s) => String(s || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
DOS.can = (perm) => !!(DOS.S.me && DOS.S.me.permissions.includes(perm));
DOS.role = () => (DOS.S.me ? DOS.S.me.user.role : "");
DOS.sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ---------- requests to the DOS server ---------- */
DOS.api = async function (path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (DOS.S.token) headers.Authorization = "Bearer " + DOS.S.token;
  const res = await fetch(path, { method: opts.method || "GET", headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (res.status === 401 && DOS.S.token && !opts.noLogout) { DOS.signOut("Your session ended. Please sign in again."); throw new Error("Signed out"); }
  const text = await res.text();
  let data = null; try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw new Error((data && data.detail) ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : `Request failed (${res.status})`);
  return data;
};

/* A stream: the server sends one JSON object per line while it works (the agent launcher uses this).
   onEvent is called for every object as soon as it arrives. Returns when the server finishes. */
DOS.stream = async function (path, body, onEvent) {
  const ctl = new AbortController(); DOS.S.streams.push(ctl);
  const res = await fetch(path, { method: "POST", signal: ctl.signal, body: JSON.stringify(body || {}),
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + DOS.S.token } });
  if (!res.ok) { let m = `Request failed (${res.status})`; try { m = (await res.json()).detail || m; } catch {} throw new Error(m); }
  const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
  try {
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let i; while ((i = buf.indexOf("\n")) >= 0) { const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1); if (line) onEvent(JSON.parse(line)); }
    }
    if (buf.trim()) onEvent(JSON.parse(buf));
  } catch (e) { if (e.name !== "AbortError") throw e; }
};

/* ---------- timers that belong to the current page (stopped when you leave it) ---------- */
DOS.every = (ms, fn) => { const id = setInterval(fn, ms); DOS.S.timers.push(id); return id; };
DOS.clearPage = () => { DOS.S.timers.forEach(clearInterval); DOS.S.timers = []; };

/* ---------- the menu: which pages each role sees ----------
   The five-layer pages are only for the Business Owner and the Operations Manager (me.layers is true).
   The server refuses those routes for every other role, so hiding them here is backed by layer 5. */
DOS.NAV = [
  { group: "Operate", items: [
    { id: "home", label: "Home", icon: "home" },
    { id: "studio", label: "Agent Studio", icon: "bot", show: (m) => m.user.role !== "technician" },
    { id: "runs", label: "Live runs", icon: "pulse", show: (m) => m.user.role !== "technician" },
    { id: "approvals", label: "Approvals", icon: "check", badge: true, show: (m) => ["owner", "operator", "approver", "auditor"].includes(m.user.role) },
    { id: "plant", label: "Plant floor", icon: "factory", show: (m) => m.plant },
    { id: "workorders", label: "Work orders", icon: "wrench", show: (m) => m.plant && m.user.role !== "auditor" },
    { id: "activity", label: "Live activity", icon: "radio", show: (m) => m.user.role !== "technician" },
    { id: "audit", label: "Audit & evidence", icon: "doc", show: (m) => m.user.role === "auditor" },
    { id: "safety", label: "Emergency stop", icon: "shield", show: (m) => m.user.role === "approver" },
  ] },
  { group: "Platform · five layers", layers: true, items: [
    { id: "layers", label: "The five layers", icon: "layers" },
    { id: "rules", label: "Rules & limits", icon: "sliders", lt: 2 },
    { id: "data", label: "Data & access", icon: "db", lt: 3 },
    { id: "versions", label: "Agent versions", icon: "git", lt: 4 },
    { id: "safety", label: "Safety & governance", icon: "shield", lt: 5 },
    { id: "audit", label: "Audit & evidence", icon: "doc", lt: 5 },
  ] },
];
DOS.navFor = function (me) {
  return DOS.NAV.filter((g) => !g.layers || me.layers)
    .map((g) => ({ ...g, items: g.items.filter((it) => !it.show || it.show(me)) }))
    .filter((g) => g.items.length);
};
DOS.allowedPage = (name) => DOS.navFor(DOS.S.me).some((g) => g.items.some((it) => it.id === name));

/* ---------- the router: #page/arg in the address bar decides what is drawn ---------- */
DOS.go = (hash) => { if (location.hash === "#" + hash) DOS.route(); else location.hash = hash; };
DOS.route = async function () {
  if (!DOS.S.token || !DOS.S.me) return;
  DOS.clearPage();
  DOS.S.streams.forEach((c) => c.abort()); DOS.S.streams = [];
  let [name, ...rest] = (location.hash || "#home").slice(1).split("/");
  if (!DOS.allowedPage(name)) name = "home";
  DOS.S.page = name;
  DOS.drawNav(name);
  const main = DOS.$("main");
  main.innerHTML = `<div class="page" id="page"></div>`;
  const el = DOS.$("page");
  if (!DOS.pages[name]) { el.innerHTML = `<div class="card"><h3>This page is not built yet</h3><p class="muted">Its file in server/console/js/ is created in Phase 11 of the upgrade guide.</p></div>`; return; }
  try { await DOS.pages[name].render(el, decodeURIComponent(rest.join("/"))); }
  catch (e) { if (e.message !== "Signed out") el.innerHTML = `<div class="card"><h3>Could not load this page</h3><p class="muted">${DOS.esc(e.message)}</p><button class="btn" onclick="DOS.route()">Try again</button></div>`; }
  window.scrollTo({ top: 0, behavior: "instant" in window ? "instant" : "auto" });
};

/* ---------- start, sign in, sign out ---------- */
DOS.boot = async function () {
  DOS.$("bootLogo").innerHTML = DOS.logo(72);
  window.addEventListener("hashchange", DOS.route);
  document.addEventListener("click", DOS.ripple);
  if (DOS.S.token) {
    try { DOS.S.me = await DOS.api("/api/app/me", { noLogout: true }); }
    catch { DOS.S.token = ""; localStorage.removeItem("dos_token"); }
  }
  setTimeout(() => DOS.$("boot").classList.add("gone"), 350);
  if (DOS.S.me) DOS.startApp(); else DOS.showLogin();
};
DOS.signIn = async function (token) {
  DOS.S.token = token; localStorage.setItem("dos_token", token);
  DOS.S.me = await DOS.api("/api/app/me");
  DOS.startApp();
};
DOS.signOut = function (msg) {
  DOS.clearPage(); DOS.S.streams.forEach((c) => c.abort()); clearInterval(DOS.S.meTimer);
  DOS.S.token = ""; DOS.S.me = null; localStorage.removeItem("dos_token");
  history.replaceState(null, "", location.pathname);
  DOS.showLogin(msg);
};
