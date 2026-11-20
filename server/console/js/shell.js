/* The app frame after sign-in: side menu (by role), top bar (mode, emergency stop, Ask DOS, you), stop banner. */
"use strict";
(() => {
  const { esc, icon } = DOS;

  DOS.startApp = function () {
    const me = DOS.S.me;
    document.documentElement.style.setProperty("--brand", me.client.accent || "#3F86FF");
    DOS.$("app").innerHTML = `
    <div class="shell">
      <aside class="side" id="side">
        <div class="brandblk">${DOS.logo(36)}<div><div class="pname">DOS</div><div class="cname">${esc(me.client.name)}</div></div></div>
        <nav class="nav" id="nav"></nav>
        <div class="foot"><div class="row" style="gap:6px">${DOS.lt(1)}${DOS.lt(2)}${DOS.lt(3)}${DOS.lt(4)}${DOS.lt(5)}</div>
          <span>DOS · DigiQuench OS · ${esc(me.agents)} agents</span><span>Gemini · Google ADK · Cloud Run</span></div>
      </aside>
      <div style="min-width:0">
        <header class="top">
          <button class="btn sm ghost mnav" id="mnav" aria-label="Menu">${icon("menu")}</button>
          <div class="crumb" id="crumb"></div><div class="grow"></div>
          <span class="mode ${me.mode === "mock" ? "sim" : ""}" title="${me.mode === "mock" ? "Scripted model with real tools and rules. Never shown as Gemini output." : "Agents call Gemini"}"><i></i>${me.mode === "mock" ? "Simulation" : "Gemini live"}</span>
          ${DOS.can("killswitch") ? `<button class="btn sm bad" id="stopBtn">${icon("stop")}<span>Emergency stop</span></button>` : ""}
          <button class="btn sm glow" id="askBtn">${icon("chat")}Ask DOS</button>
          <div class="me" id="meBtn"><span class="av">${esc(DOS.initials(me.user.name))}</span><div><div class="nm">${esc(me.user.name)}</div><div class="rl">${esc(me.user.role_name)}</div></div></div>
        </header>
        <div id="stopbar"></div>
        <main id="main"></main>
      </div>
    </div>
    <div class="menu hide" id="menu"></div>
    <aside class="drawer" id="drawer"></aside>`;
    DOS.$("mnav").onclick = () => DOS.$("side").classList.toggle("open");
    DOS.$("askBtn").onclick = () => (DOS.openAsk ? DOS.openAsk() : DOS.toast("Ask DOS arrives with js/ask.js (Phase 11)."));
    DOS.$("meBtn").onclick = (e) => { e.stopPropagation(); toggleMenu(); };
    if (!DOS.S.wired) { DOS.S.wired = true; document.addEventListener("click", () => DOS.$("menu") && DOS.$("menu").classList.add("hide")); }
    if (DOS.$("stopBtn")) DOS.$("stopBtn").onclick = () => DOS.emergency(!DOS.S.me.kill.engaged);
    drawStop();
    clearInterval(DOS.S.meTimer); DOS.S.meTimer = setInterval(refreshMe, 8000);   // badge, emergency stop and mode stay current on every page
    if (!location.hash) location.hash = "home";
    DOS.route();
  };

  DOS.drawNav = function (active) {
    const me = DOS.S.me;
    DOS.$("nav").innerHTML = DOS.navFor(me).map((g) =>
      `<div class="grp">${g.layers ? icon("layers") : ""}${esc(g.group)}</div>` + g.items.map((it, i) =>
        `<a href="#${it.id}" class="rise ${active === it.id ? "on" : ""}" style="--i:${i}">${icon(it.icon)}<span>${esc(it.label)}</span>${it.lt ? `<span class="right">${DOS.lt(it.lt)}</span>` : ""}${it.badge && me.pending ? `<em>${me.pending}</em>` : ""}</a>`).join("")).join("");
    const page = DOS.pages[active];
    DOS.$("crumb").innerHTML = `${esc(me.client.name)} / <b>${esc(page ? page.title : "Home")}</b>`;
    DOS.$("side").classList.remove("open");
  };

  async function refreshMe() {
    if (!DOS.S.token) return;
    try {
      const before = DOS.S.me; const now = await DOS.api("/api/app/me");
      DOS.S.me = now;
      if (before.pending !== now.pending || before.kill.engaged !== now.kill.engaged) { DOS.drawNav(DOS.S.page); drawStop(); }
    } catch { /* the next tick tries again */ }
  }
  DOS.refreshMe = refreshMe;

  function drawStop() {
    const k = DOS.S.me.kill || {};
    DOS.$("stopbar").innerHTML = k.engaged ? `<div class="stopbar">${icon("alert")}<span>EMERGENCY STOP ENGAGED. No agent can act. ${esc(k.reason || "")}</span>
      ${DOS.can("killswitch") ? `<button class="btn sm good right" id="releaseBtn">Release</button>` : ""}</div>` : "";
    if (DOS.$("releaseBtn")) DOS.$("releaseBtn").onclick = () => DOS.emergency(false);
    if (DOS.$("stopBtn")) DOS.$("stopBtn").querySelector("span").textContent = k.engaged ? "Release stop" : "Emergency stop";
  }

  /* Pull or release the emergency stop (Business Owner and Approver). Every agent stops at its next step. */
  DOS.emergency = async function (engage) {
    if (engage) {
      DOS.modal(`<h3>Pull the emergency stop?</h3><p class="muted">Every agent for ${esc(DOS.S.me.client.name)} stops at its next step and all waiting approvals are cancelled. The reason is recorded in the audit trail.</p>
        <label class="f" style="margin-top:12px">Reason<input class="in" id="kr" placeholder="e.g. wrong supplier prices loaded"></label>
        <div class="acts"><button class="btn" data-close>Cancel</button><button class="btn bad" id="kGo">${icon("stop")}Stop every agent</button></div>`, (sc, close) => {
        DOS.qs("#kGo", sc).onclick = async () => {
          try { const r = await DOS.api("/api/governance/kill", { method: "POST", body: { engaged: true, reason: DOS.qs("#kr", sc).value } }); close();
            DOS.toast(`Emergency stop engaged. ${r.approvals_cancelled} waiting approval(s) cancelled.`, "bad"); await refreshMe(); drawStop(); DOS.route(); }
          catch (e) { DOS.toast(e.message, "bad"); }
        };
      });
    } else if (await DOS.confirm("Release the emergency stop?", "Agents may act again under the company's rules.", "Release", "good")) {
      await DOS.api("/api/governance/kill", { method: "POST", body: { engaged: false, reason: "released" } });
      DOS.toast("Emergency stop released.", "ok"); await refreshMe(); drawStop(); DOS.route();
    }
  };

  function toggleMenu() {
    const me = DOS.S.me, m = DOS.$("menu");
    m.innerHTML = `<div style="padding:8px 10px"><b>${esc(me.user.name)}</b><div class="small muted">${esc(me.user.role_name)} · ${esc(me.client.name)}</div></div><div class="sep"></div>
      <div class="small muted" style="padding:4px 10px 8px">${me.layers ? "You see every page, including the five DOS layers." : "You see the pages your role needs. The platform layers are managed for you."}</div>
      ${me.demo ? `<button id="mSwitch">${icon("user")}Switch role (demo)</button>` : ""}
      <button id="mOut">${icon("out")}Sign out</button>`;
    m.classList.toggle("hide");
    m.onclick = (e) => e.stopPropagation();
    DOS.$("mOut").onclick = () => DOS.signOut();
    if (DOS.$("mSwitch")) DOS.$("mSwitch").onclick = () => DOS.signOut("Pick another role to see DOS through their eyes.");
  }
})();
