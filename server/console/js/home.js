/* Home: one page, drawn differently for each role.
   Business Owner and Operations Manager: the whole operation, the domains and the five-layer health strip.
   Approver: what is waiting for a decision. Technician: my repair jobs. Auditor: what happened and the evidence. */
"use strict";
(() => {
  const { esc, icon, num } = DOS;
  const GREET = () => { const h = new Date().getHours(); return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"; };

  DOS.pages.home = {
    title: "Home",
    async render(el) {
      el.innerHTML = DOS.skeleton(5);
      const me = DOS.S.me, role = me.user.role;
      const h = await DOS.api("/api/app/home");
      const k = h.kpis;
      const actions = {
        owner: `<button class="btn glow" onclick="DOS.go('studio/run-all')">${icon("play")}Run every agent</button><button class="btn" onclick="DOS.go('layers')">${icon("layers")}Five layers</button>`,
        operator: `<button class="btn glow" onclick="DOS.go('studio/run-all')">${icon("play")}Run every agent</button><button class="btn" onclick="DOS.go('runs')">${icon("pulse")}Live runs</button>`,
        approver: `<button class="btn glow" onclick="DOS.go('approvals')">${icon("check")}Open approvals${me.pending ? ` (${me.pending})` : ""}</button>`,
        technician: `<button class="btn glow" onclick="DOS.go('workorders')">${icon("wrench")}My work orders</button>`,
        auditor: `<button class="btn glow" onclick="DOS.go('audit')">${icon("doc")}Audit & evidence</button>`,
      }[role] || "";
      const sub = {
        owner: "Your operations, run by AI agents under your rules. Everything below is live.",
        operator: "Launch any agent, watch it work step by step, and keep every domain running.",
        approver: "Agents stop and wait for you whenever an action is risky. Decide with the evidence in front of you.",
        technician: "DOS finds the fault and the likely cause; you fix it. Your jobs are below.",
        auditor: "Read-only. Every run, decision and change is recorded in a tamper-evident chain.",
      }[role];
      el.innerHTML = `
        <div class="card hero rise" style="margin-bottom:18px;padding:24px">
          <div class="row" style="align-items:flex-start;position:relative;z-index:1">
            <div class="grow"><div class="eyebrow">${esc(me.client.name)} · ${esc(me.user.role_name)}</div>
              <h1 style="margin-top:8px">${GREET()}, <span class="grad">${esc(me.user.name)}</span></h1><p class="sub" style="color:var(--text2);margin:8px 0 0">${sub}</p></div>
            <div class="row">${actions}</div>
          </div>
        </div>
        ${h.kill.engaged ? `<div class="card rise" style="border-color:rgba(248,113,113,.5);margin-bottom:14px">${icon("alert")} <b>Emergency stop is engaged.</b> <span class="muted">${esc(h.kill.reason || "")}</span></div>` : ""}
        <div class="tiles" style="margin-bottom:18px">${tiles(role, k, h)}</div>
        <div id="homeBody"></div>`;
      DOS.countUp(el);
      const body = DOS.$("homeBody");
      if (role === "technician") body.innerHTML = techView(h);
      else if (role === "approver") body.innerHTML = approverView(h);
      else if (role === "auditor") body.innerHTML = auditorView(h);
      else body.innerHTML = leaderView(h, me);
      DOS.qsa("[data-run]", el).forEach((r) => (r.onclick = () => DOS.go("runs/" + r.dataset.run)));
      DOS.qsa("[data-dom]", el).forEach((r) => (r.onclick = () => DOS.go("studio/" + encodeURIComponent(r.dataset.dom))));
      DOS.qsa("[data-layer]", el).forEach((r) => (r.onclick = () => DOS.go(r.dataset.layer)));
      if (me.layers) loadStrip();
      DOS.every(15000, async () => { const n = await DOS.api("/api/app/home"); if (n.kpis.runs_today !== k.runs_today || n.kpis.pending_approvals !== k.pending_approvals) DOS.route(); });
    },
  };

  function tiles(role, k, h) {
    if (role === "technician") {
      const mine = h.my_work_orders || [];
      return [DOS.tile("My open jobs", mine.filter((w) => w.status !== "resolved").length, "assigned to you", "wrench", "var(--accent)", 0),
        DOS.tile("Closed by me", mine.filter((w) => w.status === "resolved").length, "repairs finished", "check", "var(--ok)", 1),
        DOS.tile("Open breakdowns", (h.plant || { open: [] }).open.length, "on the plant floor", "factory", "var(--bad)", 2)].join("");
    }
    const t = [
      DOS.tile("Agents live", k.agents_live, `of ${k.agents_total} available`, "bot", "var(--brand)", 0),
      DOS.tile("Runs today", k.runs_today, k.simulated_today ? `${k.simulated_today} in simulation` : DOS.S.me.mode === "mock" ? "simulation mode" : "on Gemini", "pulse", "var(--l2)", 1),
      DOS.tile("Done by agents", k.completed_today, "finished without a person", "check", "var(--ok)", 2),
      DOS.tile("Waiting for people", k.pending_approvals, "risky actions held for approval", "clock", "var(--accent)", 3),
      DOS.tile("Hours saved", k.hours_saved, `estimate: ${k.minutes_per_task} min per task`, "bolt", "var(--warn)", 4),
    ];
    if (role === "auditor") t.splice(4, 1, DOS.tile("Failed runs", k.failed_today, "each one raised an incident", "alert", "var(--bad)", 4));
    return t.join("");
  }

  const runRow = (r, i) => `<div class="item click rise" style="--i:${i}" data-run="${esc(r.id)}">${DOS.domIcon(r.vertical)}
    <div class="grow"><b>${esc(r.agent_name)}</b><div class="small muted" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(r.output || "…")}</div></div>
    <div style="text-align:right">${DOS.status(r.status)}<div class="small muted" style="margin-top:4px">${DOS.ago(r.created_at)}</div></div></div>`;
  const recent = (h) => h.recent.length ? `<div class="list">${h.recent.map(runRow).join("")}</div>` : DOS.empty("bot", "No runs yet", "Launch an agent from Agent Studio and watch it work.", `<button class="btn primary" onclick="DOS.go('studio')">Open Agent Studio</button>`);
  const apRow = (a, i) => `<div class="item click rise" style="--i:${i}" onclick="DOS.go('approvals')"><span class="ico" style="--ic:var(--accent)">${icon("clock")}</span>
    <div class="grow"><b>${esc(a.agent_name)}</b> wants to <b>${esc(DOS.title(a.tool))}</b><div class="small muted">${esc((a.why || "").slice(0, 110))}</div></div><span class="small muted">${DOS.ago(a.created_at)}</span></div>`;
  const plantCard = (h) => !h.plant ? "" : `<div class="card rise" style="--i:3"><div class="row"><h3>Plant floor</h3><button class="btn sm right" onclick="DOS.go('plant')">Open</button></div>
    ${h.plant.open.length ? `<div class="list" style="margin-top:10px">${h.plant.open.map((i) => `<div class="item"><span class="ico" style="--ic:var(--bad)">${icon("alert")}</span><div class="grow"><b>${esc(i.machine_name || i.machine)}</b>
      <div class="small muted">${esc(i.root_cause ? DOS.title(i.root_cause) + (i.confidence ? ` (${DOS.pct(i.confidence)})` : "") : "Diagnosing…")}${i.technician ? " · " + esc(i.technician) : ""}</div></div>${DOS.status(i.status)}</div>`).join("")}</div>`
      : `<p class="muted" style="margin:10px 0 0">All machines healthy. ${num(h.plant.resolved)} breakdown(s) resolved so far.</p>`}</div>`;

  function leaderView(h, me) {
    const notLive = h.kpis.agents_total - h.kpis.agents_live;
    const prep = notLive <= 0 ? "" : me.user.role === "owner"
      ? `<div class="card rise" style="margin-bottom:14px;border-color:color-mix(in srgb,var(--accent) 50%,transparent)"><div class="row"><span class="ico" style="--ic:var(--accent)">${icon("flag")}</span>
          <div class="grow"><b>${notLive} of ${h.kpis.agents_total} agents are not live yet.</b><div class="small muted">One click switches every agent on, connects its data, records your risk acceptance and passes each one through the governance and evaluation gates.</div></div>
          <button class="btn glow" onclick="DOS.go('studio/prepare')">${icon("flag")}Prepare all agents</button></div></div>`
      : `<div class="card rise" style="margin-bottom:14px"><div class="row"><span class="ico" style="--ic:var(--accent)">${icon("flag")}</span><div class="grow"><b>${notLive} agents are not live yet.</b>
          <div class="small muted">High-risk agents need the Business Owner's one-time risk acceptance (Agent Studio, Prepare all agents). Low and medium-risk agents you can launch directly.</div></div></div></div>`;
    return `${prep}
      ${me.layers ? `<div class="card rise" style="margin-bottom:14px"><div class="row"><h3>Platform health</h3><span class="small muted">the five DOS layers, live</span><button class="btn sm right" onclick="DOS.go('layers')">${icon("layers")}Open</button></div>
        <div class="flowlayers" id="strip" style="margin-top:12px">${'<div class="skel" style="height:70px"></div>'.repeat(5)}</div></div>` : ""}
      <div class="grid g2" style="margin-bottom:14px">
        <div class="card rise" style="--i:1"><div class="row"><h3>Runs in the last 12 hours</h3><span class="small muted right">green = finished by the agent</span></div><div style="margin-top:14px">${DOS.bars(h.hours)}</div>
          <div class="row small muted" style="justify-content:space-between;margin-top:6px"><span>12 h ago</span><span>now</span></div></div>
        <div class="card rise" style="--i:2"><div class="row"><h3>Waiting for people</h3><button class="btn sm right" onclick="DOS.go('approvals')">All approvals</button></div>
          <div class="list" style="margin-top:10px">${h.approvals.length ? h.approvals.map(apRow).join("") : `<p class="muted">Nothing is waiting. Agents finished everything within your rules.</p>`}</div></div>
      </div>
      <h2>Domains</h2>
      <div class="grid g4" style="margin-bottom:14px">${h.domains.map((d, i) => `<div class="card hover rise" style="--i:${i}" data-dom="${esc(d.vertical)}"><div class="domain">${DOS.domIcon(d.vertical)}<div class="grow"><b>${esc(d.vertical)}</b>
        <div class="small muted">${d.live} of ${d.agents} agents live · ${d.runs} runs today</div></div></div><div class="meter" style="margin-top:12px"><i style="width:${d.agents ? (d.live / d.agents) * 100 : 0}%"></i></div></div>`).join("")}</div>
      <div class="grid g2"><div class="card rise"><div class="row"><h3>Latest runs</h3><button class="btn sm right" onclick="DOS.go('runs')">All runs</button></div><div style="margin-top:10px">${recent(h)}</div></div>${plantCard(h) || `<div class="card rise"><h3>Ask DOS</h3><p class="muted">Ask in plain English: “Which items are waiting for approval?”, “Explain the last run”, “Did anything fail today?”</p><button class="btn glow" onclick="DOS.openAsk()">${icon("chat")}Ask DOS</button></div>`}</div>`;
  }

  function approverView(h) {
    return `<div class="split"><div class="card rise"><div class="row"><h3>Waiting for your decision</h3><button class="btn sm primary right" onclick="DOS.go('approvals')">Decide now</button></div>
        <div class="list" style="margin-top:10px">${h.approvals.length ? h.approvals.map(apRow).join("") : `<p class="muted">Nothing waiting. You will see a badge on Approvals when an agent needs you.</p>`}</div></div>
      <div class="grid">${plantCard(h)}<div class="card rise"><h3>Latest runs</h3><div style="margin-top:10px">${recent(h)}</div></div></div></div>`;
  }

  function techView(h) {
    const mine = h.my_work_orders || [];
    return `<div class="split"><div class="card rise"><div class="row"><h3>My jobs</h3><button class="btn sm primary right" onclick="DOS.go('workorders')">Open work orders</button></div>
        <div class="list" style="margin-top:10px">${mine.length ? mine.map((w, i) => `<div class="item click rise" style="--i:${i}" onclick="DOS.go('workorders')"><span class="ico" style="--ic:var(--accent)">${icon("wrench")}</span>
          <div class="grow"><b>${esc(w.machine_name)}</b> · ${esc(w.title)}<div class="small muted">${esc(w.priority)} priority · part ${esc(w.part || "none")}</div></div>${DOS.status(w.status)}</div>`).join("")
          : `<p class="muted">No jobs assigned to you. When a machine breaks down, DOS dispatches the right technician here within seconds.</p>`}</div></div>
      <div class="grid">${plantCard(h)}</div></div>`;
  }

  function auditorView(h) {
    return `<div class="grid g2"><div class="card rise"><h3>Latest runs</h3><div style="margin-top:10px">${recent(h)}</div></div>
      <div class="card rise" style="--i:1"><h3>Evidence</h3><p class="muted">Every agent action, approval, data read and rule change is chained by hash. Verify the chain and download the evidence pack.</p>
        <div class="row"><button class="btn primary" onclick="DOS.go('audit')">${icon("doc")}Audit & evidence</button><button class="btn" onclick="DOS.go('activity')">${icon("radio")}Live activity</button></div></div></div>`;
  }

  async function loadStrip() {
    try {
      const L = await DOS.api("/api/app/layers");
      const s = DOS.$("strip"); if (!s) return;
      const pages = { 1: "home", 2: "rules", 3: "data", 4: "studio", 5: "safety" };
      s.innerHTML = L.layers.map((l, i) => `<div class="rise" style="--i:${i};--lc:var(--l${l.n});cursor:pointer" data-layer="${pages[l.n]}"><div class="row"><span class="lt L${l.n}">L${l.n}</span><span class="chip dot ${l.status === "ok" ? "ok" : l.status === "stop" ? "bad" : "warn"}">${l.status === "ok" ? "Healthy" : l.status === "stop" ? "Stopped" : "Check"}</span></div>
        <b style="font-size:14px;margin-top:8px;color:var(--text)">${esc(l.name)}</b><div class="small muted">${esc(l.facts[0])}</div></div>`).join("");
      DOS.qsa("[data-layer]", s).forEach((r) => (r.onclick = () => DOS.go(r.dataset.layer)));
    } catch { /* the strip is optional */ }
  }
})();
