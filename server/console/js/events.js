/* Event watch: every agent shown as a listener. What it waits for, where events come from, the events queued for it,
   and one click to deliver the next event. The run streams in place; when it ends the agent goes back to listening.
   Manufacturing agents listen to the live plant, so a machine alarm appears here by itself. */
"use strict";
(() => {
  const { esc, icon } = DOS;
  let state = { vertical: "all", auto: false, busy: new Set(), last: {} };

  DOS.pages.events = {
    title: "Event watch",
    async render(el, arg) {
      state.vertical = arg || state.vertical || "all";
      const me = DOS.S.me, domains = ["all", ...(me.client.verticals || [])];
      el.innerHTML = DOS.header("Agents at work", "Event watch",
        "Every agent here is switched on and listening. Each waits for its own kind of event: a transaction alert, a KYC upload, a machine alarm, a supplier invoice, a schedule. Deliver an event and watch the agent pick it up.",
        `<div class="seg" id="wMode"><button data-m="mock" class="on">Simulation</button><button data-m="live">Gemini</button></div>
         <label class="row small muted" style="gap:6px;cursor:pointer"><input type="checkbox" id="wAuto" ${state.auto ? "checked" : ""}> Auto-feed events</label>`) +
        `<div class="seg" id="wDom" style="margin-bottom:14px">${domains.map((d) => `<button data-v="${esc(d)}" class="${d === state.vertical ? "on" : ""}">${d === "all" ? "All domains" : esc(d)}</button>`).join("")}</div>
         <div id="wStrip"></div><div id="wGrid">${DOS.skeleton(4)}</div>`;
      DOS.qsa("#wDom button").forEach((b) => (b.onclick = () => DOS.go("events/" + b.dataset.v)));
      DOS.qsa("#wMode button").forEach((b) => (b.onclick = () => DOS.qsa("#wMode button").forEach((x) => x.classList.toggle("on", x === b))));
      DOS.$("wAuto").onchange = (e) => { state.auto = e.target.checked; DOS.toast(state.auto ? "Auto-feed on: one event every 20 seconds, one agent at a time." : "Auto-feed off.", "ok"); };
      await load(true);
      DOS.every(6000, () => load(false));
      DOS.every(20000, autoFeed);
    },
  };

  let data = null;
  async function load(first) {
    const w = await DOS.api(`/api/app/events?vertical=${encodeURIComponent(state.vertical)}`);
    data = w;
    const grid = DOS.$("wGrid"); if (!grid) return;
    const listening = w.agents.length, queued = w.queued, alarms = w.alarms.length;
    DOS.$("wStrip").innerHTML = `<div class="grid g4" style="margin-bottom:14px">
      ${tile("radio", "Agents listening", listening, "var(--ok)")}${tile("clock", "Events queued", queued, "var(--accent)")}
      ${tile("factory", "Machines in alarm", alarms, alarms ? "var(--bad)" : "var(--muted)")}${tile("pulse", "Working now", state.busy.size, "var(--brand)")}</div>`;
    if (first) {
      grid.innerHTML = `<div class="grid g3">${w.agents.map((a, i) => card(a, i, w.can_run)).join("")}</div>`;
      DOS.qsa("[data-deliver]", grid).forEach((b) => (b.onclick = () => deliver(b.dataset.deliver, +b.dataset.q || 0)));
    } else {
      w.agents.forEach((a) => { const c = DOS.$("ew-" + a.id); if (c && !state.busy.has(a.id)) refreshQueue(c, a); });
    }
  }

  const tile = (ic, label, n, col) => `<div class="card" style="padding:14px 16px"><div class="row"><span class="ico" style="--ic:${col}">${icon(ic)}</span>
    <div><div class="small muted">${label}</div><b style="font-size:22px">${n}</b></div></div></div>`;

  function queueHtml(a) {
    return a.queue.map((e, k) => `<div class="evq ${k ? "" : "next"}">
      <div class="row" style="gap:8px"><span class="chip ${e.rehearsal ? "warn" : k ? "" : "info"}">${e.rehearsal ? "Rehearsal" : k ? "Queued" : "Next"}</span><b class="small">${esc(e.record || a.event)}</b>
        ${e.sample ? "" : `<span class="chip violet" title="${esc(e.note)}">new</span>`}
        <span class="grow"></span>${a.can_run !== false ? `<button class="btn sm ${k || e.rehearsal ? "" : "primary"}" data-deliver="${esc(a.id)}" data-q="${k}">${icon("play")}${e.rehearsal ? "Rehearse" : "Deliver"}</button>` : ""}</div>
      ${e.fields.length ? `<div class="evf">${e.fields.slice(0, 3).map(([k2, v]) => `<span><i>${esc(k2)}</i>${esc(v)}</span>`).join("")}</div>` : ""}
      ${e.note && e.sample ? `<div class="small muted" style="margin-top:4px">${esc(e.note)}</div>` : ""}</div>`).join("");
  }

  const idle = (a) => !a.queue.some((e) => !e.rehearsal);

  function card(a, i, canRun) {
    a.can_run = canRun;
    const last = a.last ? `${DOS.status(a.last.status)} <span class="small muted">${DOS.ago(a.last.created_at)}${a.last.simulated ? " · simulated" : ""}</span>` : `<span class="small muted">No event handled yet</span>`;
    return `<div class="card ew rise" id="ew-${esc(a.id)}" style="--i:${i}">
      <div class="row"><div class="radar ${idle(a) ? "idle" : ""}"><i></i>${icon(a.icon)}</div>
        <div class="grow"><b>${esc(a.name)}</b><div class="small muted">${esc(a.vertical)}${a.tier === "hero" ? " · hero" : ""}</div></div>
        <span class="chip ${idle(a) ? "warn" : "ok"} dot ewstate">${idle(a) ? "Waiting for an event" : "Listening"}</span></div>
      <div class="ewfor"><span>Waiting for</span><b>${esc(a.event)}</b><small>${esc(a.waiting_for)}</small><small class="muted">${icon("radio")} ${esc(a.source)}${a.schedule ? " · " + esc(a.schedule) : ""}</small></div>
      <div class="small ewhint ${a.hint ? "" : "hide"}" style="color:var(--warn)">${icon("alert")} ${esc(a.hint || "")}</div>
      <div class="evlist">${queueHtml(a)}</div>
      <div class="ewrun hide"><div class="ewbar"><i></i></div><div class="small ewstage muted">Picking up the event</div><div class="trace mini"></div></div>
      <div class="row ewlast" style="margin-top:10px;gap:8px">${last}</div></div>`;
  }

  function refreshQueue(c, a) {
    const sig = JSON.stringify(a.queue.map((e) => e.id)) + (a.last ? a.last.id : "");
    if (c.dataset.sig === sig) return; c.dataset.sig = sig;
    a.can_run = data.can_run;
    DOS.qs(".evlist", c).innerHTML = queueHtml(a);
    DOS.qs(".radar", c).classList.toggle("idle", idle(a));
    const stc = DOS.qs(".ewstate", c); stc.className = `chip ${idle(a) ? "warn" : "ok"} dot ewstate`; stc.textContent = idle(a) ? "Waiting for an event" : "Listening";
    const h = DOS.qs(".ewhint", c); if (h) h.classList.toggle("hide", !a.hint);
    if (a.last) DOS.qs(".ewlast", c).innerHTML = `${DOS.status(a.last.status)} <span class="small muted">${DOS.ago(a.last.created_at)}${a.last.simulated ? " · simulated" : ""}</span>`;
    DOS.qsa("[data-deliver]", c).forEach((b) => (b.onclick = () => deliver(b.dataset.deliver, +b.dataset.q || 0)));
  }

  const KIND = { model: "Model", tool: "Tool", skill: "Skill", data: "Data", config: "Rule", guardrail: "Guardrail", approval: "Approval" };
  const mini = (st) => `<div class="ms"><span class="lt L${st.layer || 4}">L${st.layer || 4}</span><b>${esc(KIND[st.kind] || st.kind)}</b><span>${esc(DOS.title(st.name || ""))}</span>
    ${st.status && st.status !== "ok" && st.status !== "applied" ? `<em class="${/error|refused|denied|blocked/.test(st.status) ? "bad" : ""}">${esc(st.status)}</em>` : ""}</div>`;
  const STAGE_TEXT = { rules: "Company rules applied", data: "Data connected", risk: "Risk checked", gate: "Governance gate", eval: "Evaluation gate", run: "Agent at work" };

  async function deliver(id, q) {
    if (state.busy.has(id)) return;
    const a = data.agents.find((x) => x.id === id), ev = a && a.queue[q]; if (!ev) return;
    const c = DOS.$("ew-" + id); state.busy.add(id);
    const mode = DOS.qs("#wMode button.on") ? DOS.qs("#wMode button.on").dataset.m : "mock";
    c.classList.add("busy"); DOS.qs(".ewstate", c).className = "chip info dot ewstate"; DOS.qs(".ewstate", c).textContent = "Handling event";
    const run = DOS.qs(".ewrun", c), trace = DOS.qs(".trace", run), stage = DOS.qs(".ewstage", run), bar = DOS.qs(".ewbar i", run);
    run.classList.remove("hide"); trace.innerHTML = ""; DOS.qsa("[data-deliver]", c).forEach((b) => (b.disabled = true));
    let n = 0, final = null, k = 0;
    try {
      await DOS.stream(`/api/app/launch/${encodeURIComponent(id)}`, { input: ev.input, mode }, (e) => {
        if (e.type === "stage") { k = Math.max(k, Object.keys(STAGE_TEXT).indexOf(e.stage) + 1); bar.style.width = `${Math.round(k / 6 * 100)}%`;
          stage.textContent = `${STAGE_TEXT[e.stage] || e.stage}: ${e.detail || e.status}`; stage.style.color = e.status === "blocked" || e.status === "failed" ? "var(--bad)" : ""; }
        if (e.type === "step" && n < 60) { trace.insertAdjacentHTML("beforeend", mini(e.step)); n++; trace.scrollTop = 1e9; }
        if (e.type === "run") final = e.run;
      });
    } catch (e) { DOS.toast(e.message, "bad"); }
    state.busy.delete(id); c.classList.remove("busy");
    DOS.qs(".ewstate", c).className = `chip ${idle(a) ? "warn" : "ok"} dot ewstate`; DOS.qs(".ewstate", c).textContent = idle(a) ? "Waiting for an event" : "Listening";
    DOS.qsa("[data-deliver]", c).forEach((b) => (b.disabled = false));
    if (final) {
      DOS.qs(".ewlast", c).innerHTML = `<button class="btn sm" onclick="DOS.go('runs/${esc(final.id)}')">${icon("pulse")}Open full trace</button>`;
      stage.innerHTML = DOS.result(final, { agent: a.name }); stage.style.color = "";
      DOS.animateResult(stage);
      bar.style.width = "100%";
    }
    DOS.refreshMe();
  }

  async function autoFeed() {
    if (!state.auto || !data || !DOS.$("wGrid") || state.busy.size) return;
    const ready = data.agents.filter((a) => !idle(a) && !state.busy.has(a.id));
    if (!ready.length) return;
    const pick = ready[Math.floor(Math.random() * ready.length)];
    DOS.$("ew-" + pick.id).scrollIntoView({ behavior: "smooth", block: "center" });
    deliver(pick.id, 0);
  }
})();
