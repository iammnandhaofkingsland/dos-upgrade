/* Agent Studio: every agent of every domain, launched end to end with one click.
   One agent: a drawer shows the six-stage journey (rules, data, risk, gate, evaluation, run) and the live trace.
   Many agents: "Run every agent" and "Run this domain" open Mission Control, which runs them a few at a time. */
"use strict";
(() => {
  const { esc, icon, num } = DOS;
  const ST = { data: null, filter: "all", q: "", agents: {} };
  const STAGES = [["rules", "Rules", "rules", 2], ["data", "Data", "db", 3], ["risk", "Risk", "shield", 5], ["gate", "Gate", "lock", 5], ["eval", "Evaluation", "flag", 4], ["run", "Agent at work", "bot", 4]];
  const KIND = { config: ["rules", 2, "Rule read"], data: ["db", 3, "Data read"], model: ["model", 4, "Gemini"], tool: ["tool", 4, "Tool"], skill: ["doc", 4, "Skill"],
    guardrail: ["shield", 5, "Guardrail"], approval: ["check", 5, "Approval"], governance: ["shield", 5, "Governance"] };

  /* One line of a run's trace, coloured by the layer that produced it. Used here and on Live runs. */
  DOS.stepRow = (s, i = 0) => {
    let [ic, layer, label] = KIND[s.kind] || ["spark", 4, s.kind];
    const sim = s.kind === "model" && String(s.name).startsWith("mock");
    if (sim) label = "Simulated model";                     // never shown as Gemini output
    const name = s.kind === "model" ? (s.status === "error" ? "Model error" : sim ? "Model step" : "Gemini thought") : DOS.title(s.name);
    const what = s.detail || (s.kind === "model" ? `${num(s.input_tokens || 0)} in / ${num(s.output_tokens || 0)} out tokens${s.latency_ms ? " · " + s.latency_ms + " ms" : ""}` : "") || s.output || s.input || s.value || "";
    return `<div class="tstep st-${esc(s.status || "ok")}" style="--lc:var(--l${layer});animation-delay:${Math.min(i, 8) * 25}ms"><span class="ti">${icon(ic)}</span>
      <div style="min-width:0"><div class="tn">${esc(name)} <span class="small muted">· ${label}</span></div><div class="td" title="${esc(what)}">${esc(String(what).slice(0, 220))}</div></div>
      <div class="row" style="gap:6px">${s.status && !["ok", "read", "applied"].includes(s.status) ? DOS.status(s.status === "awaiting_approval" ? "pending" : s.status) : ""}<span class="lt L${layer}">L${layer}</span></div></div>`;
  };

  DOS.pages.studio = {
    title: "Agent Studio",
    async render(el, arg) {
      el.innerHTML = DOS.skeleton(4);
      ST.data = await DOS.api("/api/app/studio");
      ST.filter = arg && arg !== "run-all" && arg !== "prepare" ? arg : "all";
      const d = ST.data, total = d.domains.reduce((n, g) => n + g.agents.length, 0), live = d.domains.reduce((n, g) => n + g.agents.filter((a) => a.state === "live").length, 0);
      const can = d.can_run;
      el.innerHTML = DOS.header("Layer 4 · AI agents", `Agent Studio`, `${total} agents across ${d.domains.length} domains, ${live} live. Click any agent to launch it end to end and watch every step, or run a whole domain at once.`,
        can ? `${d.can_prepare ? `<button class="btn" id="prepAll">${icon("flag")}Prepare all agents</button>` : ""}<button class="btn glow" id="runAll">${icon("play")}Run every agent</button>` : `<span class="chip">Read-only for your role</span>`) + `
        <div id="mission"></div>
        <div class="toolbar"><div class="seg" id="doms"><button data-v="all">All · ${total}</button>${d.domains.map((g) => `<button data-v="${esc(g.vertical)}">${esc(g.vertical)} · ${g.agents.length}</button>`).join("")}</div>
          <div class="search right">${icon("search")}<input class="in" id="q" placeholder="Search agents"></div>
          ${can ? `<button class="btn sm" id="runDom" style="display:none">${icon("play")}Run this domain</button>` : ""}</div>
        <div id="grid"></div>`;
      DOS.qsa("#doms button").forEach((b) => (b.onclick = () => { ST.filter = b.dataset.v; history.replaceState(null, "", "#studio" + (ST.filter === "all" ? "" : "/" + encodeURIComponent(ST.filter))); drawGrid(); }));
      DOS.$("q").oninput = (e) => { ST.q = e.target.value.toLowerCase(); drawGrid(); };
      if (can) {
        DOS.$("runAll").onclick = () => mission("all", true);
        DOS.$("runDom").onclick = () => mission(ST.filter, true);
        if (DOS.$("prepAll")) DOS.$("prepAll").onclick = () => mission("all", false);
      }
      drawGrid();
      if (arg === "run-all" && can) mission("all", true);
      if (arg === "prepare" && d.can_prepare) mission("all", false);
    },
  };

  function drawGrid() {
    DOS.qsa("#doms button").forEach((b) => b.classList.toggle("on", b.dataset.v === ST.filter));
    if (DOS.$("runDom")) { DOS.$("runDom").style.display = ST.filter === "all" ? "none" : ""; DOS.$("runDom").innerHTML = `${icon("play")}Run all ${esc(ST.filter)}`; }
    const groups = ST.data.domains.filter((g) => ST.filter === "all" || g.vertical === ST.filter);
    let i = 0;
    DOS.$("grid").innerHTML = groups.map((g) => {
      const list = g.agents.filter((a) => !ST.q || (a.name + a.tagline + a.problem).toLowerCase().includes(ST.q));
      if (!list.length) return "";
      const col = (DOS.DOMAIN[g.vertical] || [])[1];
      return `<h2 class="row">${DOS.domIcon(g.vertical)}${esc(g.vertical)} <span class="small muted">${list.length} agents</span></h2><div class="agrid">${list.map((a) => card(a, col, i++)).join("")}</div>`;
    }).join("") || DOS.empty("search", "No agent matches", "Try another word.");
    DOS.qsa(".agent").forEach((c) => (c.onclick = () => openLaunch(c.dataset.id)));
  }

  const card = (a, col, i) => `<div class="agent rise ${a.tier === "hero" ? "hero" : ""}" style="--i:${Math.min(i, 20)};--ac:${col}" data-id="${esc(a.id)}" id="ag-${esc(a.id)}">
    <span class="state ${a.state === "live" ? "live" : ""}"></span>
    <div class="top2"><span class="av2">${esc(DOS.initials(a.name.replace(/([a-z])([A-Z])/g, "$1 $2")))}</span><div><b>${esc(a.name)}</b><div class="small muted">${esc(a.autonomy === "auto" ? "Acts on its own" : a.autonomy === "approve" ? "Asks before risky actions" : "Suggests only")}</div></div></div>
    <p>${esc(a.tagline)}</p>
    <div class="foot2">${DOS.status(a.state)}${DOS.status(a.risk)}${a.approvals.length ? `<span class="chip">${a.approvals.length} need approval</span>` : ""}${a.last_run ? `<span class="chip small">last: ${esc(DOS.ago(a.last_run.created_at))}</span>` : ""}</div>
    <span class="bar"></span></div>`;

  const findAgent = (id) => { for (const g of ST.data.domains) { const a = g.agents.find((x) => x.id === id); if (a) return [a, g.vertical]; } return [null, null]; };

  /* ---------------------------------------------------------------- one agent, end to end */
  function openLaunch(id) {
    const [a, vertical] = findAgent(id); if (!a) return;
    const me = DOS.S.me, can = ST.data.can_run, dr = DOS.$("drawer");
    dr.className = "drawer wide open";
    dr.innerHTML = `<div class="dhead">${DOS.domIcon(vertical)}<div class="grow"><b style="font-size:16px">${esc(a.name)}</b><div class="small muted">${esc(vertical)} · ${esc(a.model)} · ${esc(a.autonomy)}</div></div>
        ${DOS.status(a.risk)}<button class="btn sm ghost" id="dClose">${icon("x")}</button></div>
      <div class="dbody">
        <p style="margin:0;color:var(--text2)">${esc(a.tagline)}</p>
        <div class="seg"><button class="on" data-t="go">Launch</button><button data-t="about">How it works</button></div>
        <div id="tGo">
          ${can ? `<label class="f">The request (edit it if you like)<textarea class="in" id="ask" rows="3">${esc(a.ask)}</textarea></label>
          <div class="row" style="margin-top:10px">${me.mode === "live" ? `<div class="seg" id="mode"><button class="on" data-m="live">Gemini</button><button data-m="mock">Simulation</button></div>` : `<span class="chip warn">Simulation mode: scripted model, real tools and rules</span>`}
            <button class="btn glow lg right" id="goBtn">${icon("play")}Launch ${esc(a.name)}</button></div>` : `<div class="card"><b>Your role can watch agents but not start them.</b><p class="muted">The Operations Manager or Business Owner launches agents. You will see their runs on Live runs.</p></div>`}
          <div class="card" style="margin-top:14px"><div class="pipe" id="pipe">${STAGES.map(([k, l, ic, n]) => `<div class="node" data-s="${k}"><span class="dotn">${icon(ic)}</span><span class="nl">${l} ${DOS.lt(n)}</span><span class="nd" id="nd-${k}">waiting</span></div>`).join("")}</div></div>
          <div class="grid g2" style="margin-top:14px;align-items:start"><div><h3 style="margin-bottom:8px">Live trace <span class="small muted" id="tcount"></span></h3><div class="trace" id="trace"><p class="muted small">Every model call, tool call, rule read, data read and guardrail decision appears here as it happens.</p></div></div>
            <div><h3 style="margin-bottom:8px">Result</h3><div id="result"><p class="muted small">The agent's answer and anything waiting for a person appear here.</p></div></div></div>
        </div>
        <div id="tAbout" class="hide">${about(a)}</div>
      </div>`;
    DOS.$("dClose").onclick = () => dr.classList.remove("open");
    DOS.qsa(".dbody > .seg button", dr).forEach((b) => (b.onclick = () => { DOS.qsa(".dbody > .seg button", dr).forEach((x) => x.classList.toggle("on", x === b)); DOS.$("tGo").classList.toggle("hide", b.dataset.t !== "go"); DOS.$("tAbout").classList.toggle("hide", b.dataset.t !== "about"); }));
    if (DOS.$("mode")) DOS.qsa("#mode button").forEach((b) => (b.onclick = () => DOS.qsa("#mode button").forEach((x) => x.classList.toggle("on", x === b))));
    if (DOS.$("goBtn")) DOS.$("goBtn").onclick = () => launch(a);
  }

  const about = (a) => `<dl class="kv"><dt>Problem</dt><dd>${esc(a.problem)}</dd><dt>Used by</dt><dd>${esc(a.users)}</dd><dt>Starts when</dt><dd>${esc(a.trigger)}</dd>
    <dt>Tools</dt><dd>${a.tools.map((t) => `<span class="chip" style="margin:0 4px 4px 0">${a.approvals.includes(t) ? icon("lock") : ""}${esc(t)}</span>`).join("")}</dd>
    <dt>Needs a person for</dt><dd>${a.approvals.length ? a.approvals.map((t) => esc(DOS.title(t))).join(", ") : "Nothing: low-risk actions only"}</dd>
    <dt>Measured by</dt><dd>${a.kpis.map(esc).join(" · ")}</dd><dt>Guardrails</dt><dd>${a.guardrails.map(esc).join(" · ")}</dd></dl>`;

  function setNode(stage, status, detail) {
    const n = DOS.qs(`#pipe .node[data-s="${stage}"]`); if (!n) return;
    n.className = "node " + status;
    const d = DOS.$("nd-" + stage); if (d) { d.textContent = detail || status; d.title = detail || ""; }
  }

  async function launch(a) {
    const btn = DOS.$("goBtn"); btn.disabled = true; btn.innerHTML = `<span class="spinner"></span>Working`;
    STAGES.forEach(([k]) => setNode(k, "", "waiting"));
    const trace = DOS.$("trace"); trace.innerHTML = ""; DOS.$("result").innerHTML = `<div class="skel" style="height:90px"></div>`;
    const mode = DOS.$("mode") ? DOS.qs("#mode button.on").dataset.m : null;
    let steps = 0, final = null;
    try {
      await DOS.stream(`/api/app/launch/${encodeURIComponent(a.id)}`, { input: DOS.$("ask").value, mode }, (ev) => {
        if (ev.type === "stage") setNode(ev.stage, ev.status, ev.detail);
        if (ev.type === "step") { if (!steps) trace.innerHTML = ""; trace.insertAdjacentHTML("beforeend", DOS.stepRow(ev.step, steps++)); trace.scrollTop = 1e9; DOS.$("tcount").textContent = `· ${steps} steps`; }
        if (ev.type === "run") final = ev.run;
      });
    } catch (e) { DOS.toast(e.message, "bad"); }
    btn.disabled = false; btn.innerHTML = `${icon("refresh")}Launch again`;
    if (final && final.status === "waiting_approval") setNode("run", "wait", "Waiting for a person to approve");
    if (final) showResult(final, a); else DOS.$("result").innerHTML = `<div class="answer bad">The run did not start. Check the stage marked in red above.</div>`;
    DOS.refreshMe();
  }

  async function showResult(run, a) {
    const box = DOS.$("result");
    const waiting = (run.approvals || []).filter((x) => x.status === "pending");
    const cls = run.status === "completed" ? "" : run.status === "waiting_approval" ? "wait" : "bad";
    box.innerHTML = `<div class="row" style="margin-bottom:8px">${DOS.status(run.status)}${DOS.simChip(run.simulated)}<span class="small muted">${num(run.latency_ms)} ms · ${num(run.model_calls)} model calls · ${num(run.tool_calls)} tool calls · ${DOS.inr(run.cost_inr)}</span></div>
      <div class="answer ${cls}" id="ans"></div>
      ${waiting.map((w) => `<div class="apcard" style="margin-top:10px" id="ap-${esc(w.id)}"><div class="row"><span class="ico" style="--ic:var(--accent)">${icon("clock")}</span><div class="grow"><b>Waiting for a person: ${esc(DOS.title(w.tool))}</b><div class="small muted">${esc(w.why || "")}</div></div></div>
        <div class="args">${Object.entries(w.args || {}).slice(0, 6).map(([k, v]) => `<div><span>${esc(DOS.title(k))}</span><b>${esc(typeof v === "object" ? JSON.stringify(v) : v)}</b></div>`).join("")}</div>
        ${DOS.can("approval.decide") ? `<div class="row"><button class="btn good" data-ok="${esc(w.id)}">${icon("check")}Approve</button><button class="btn bad" data-no="${esc(w.id)}">${icon("x")}Reject</button><span class="small muted">You are deciding as ${esc(DOS.S.me.user.role_name)}.</span></div>`
          : `<p class="small muted" style="margin:0">An Approver decides this on the Approvals page.</p>`}</div>`).join("")}
      <div class="row" style="margin-top:10px"><button class="btn sm" onclick="DOS.go('runs/${esc(run.id)}')">${icon("pulse")}Open full trace</button></div>`;
    await DOS.typewrite(DOS.$("ans"), run.output || run.error || (run.status === "waiting_approval" ? "The agent has prepared the action and is waiting for a person to approve it." : "No answer."));
    if (run.status === "completed") { const r = box.getBoundingClientRect(); DOS.confetti(r.left + r.width / 2, r.top + 40); }
    DOS.qsa("[data-ok],[data-no]", box).forEach((b) => (b.onclick = () => decide(b.dataset.ok || b.dataset.no, !!b.dataset.ok, run, a)));
  }

  async function decide(id, approved, run, a) {
    try {
      await DOS.api(`/api/approvals/${encodeURIComponent(id)}/decision`, { method: "POST", body: { approved, note: approved ? "Approved in Agent Studio" : "Rejected in Agent Studio" } });
      DOS.$("ap-" + id).classList.add("gone");
      DOS.toast(approved ? "Approved. The agent is finishing the task." : "Rejected. The agent will not do it.", approved ? "ok" : "");
      setNode("run", "running", "Continuing after the decision");
      let r; for (let i = 0; i < 60; i++) { await DOS.sleep(500); r = await DOS.api(`/api/runs/${encodeURIComponent(run.id)}`); if (r.status !== "running") break; }
      DOS.$("trace").innerHTML = r.steps.map((s, i) => DOS.stepRow(s, i)).join(""); DOS.$("trace").scrollTop = 1e9;
      setNode("run", r.status === "failed" ? "failed" : "done", r.status === "completed" ? "Run done" : DOS.title(r.status));
      showResult({ ...r, approvals: r.approvals }, a); DOS.refreshMe();
    } catch (e) { DOS.toast(e.message, "bad"); }
  }

  /* ---------------------------------------------------------------- many agents: Mission Control */
  async function mission(vertical, run) {
    const all = ST.data.domains.filter((g) => vertical === "all" || g.vertical === vertical).flatMap((g) => g.agents.map((a) => ({ ...a, vertical: g.vertical })));
    const what = vertical === "all" ? `all ${all.length} agents in ${ST.data.domains.length} domains` : `the ${all.length} ${vertical} agents`;
    const sim = DOS.S.me.mode === "mock";
    const ok = await DOS.confirm(run ? "Run " + what + "?" : "Prepare " + what + "?",
      run ? `Each agent is prepared if needed (rules, data, risk, gate, evaluation) and then given its standard request. ${ST.data.parallel} run at a time. ${sim ? "Simulation mode: scripted model, real tools and rules." : "Runs use Gemini; if Gemini's rate limit is reached, that agent runs again in simulation and is marked Simulated."} Risky actions wait on Approvals.`
        : `Every agent is switched on, connected to its data, risk-accepted by you (High-risk agents) and deployed through the governance and evaluation gates. Bulk evaluations use ${ST.data.bulk_eval_mode === "mock" ? "simulated checks (marked so)" : "Gemini"}.`, run ? "Run them" : "Prepare them", "primary");
    if (!ok) return;
    const S = Object.fromEntries(all.map((a) => [a.id, "q"]));
    const cnt = () => { const c = { q: 0, p: 0, r: 0, d: 0, w: 0, x: 0 }; Object.values(S).forEach((v) => c[v]++); return c; };
    const box = DOS.$("mission");
    box.innerHTML = `<div class="card hero rise" style="margin-bottom:18px"><div class="mission" style="position:relative;z-index:1"><div id="mRing">${DOS.ring(0, "var(--brand)", 180, "complete")}</div>
      <div><div class="row"><h3>Mission Control · ${run ? "running" : "preparing"} ${esc(what)}</h3><span class="right small muted" id="mTime">0 s</span></div>
        <div class="counts" style="margin-top:12px" id="mCounts"></div><div class="mini" style="margin-top:12px;max-height:230px;overflow:auto" id="mTiles">${all.map((a) => `<div class="q" id="mt-${esc(a.id)}" title="${esc(a.vertical)}"><i></i><span>${esc(a.name)}</span></div>`).join("")}</div>
        <div class="feed small" style="margin-top:10px;max-height:110px" id="mFeed"></div></div></div></div>`;
    box.scrollIntoView({ behavior: "smooth", block: "start" });
    const t0 = Date.now(), clock = setInterval(() => (DOS.$("mTime") ? (DOS.$("mTime").textContent = Math.round((Date.now() - t0) / 1000) + " s") : clearInterval(clock)), 500);
    const LBL = { q: "Queued", p: "Preparing", r: "Working", d: run ? "Done" : "Live", w: "Waiting for people", x: "Stopped or failed" };
    const draw = () => {
      const c = cnt(), done = c.d + c.w + c.x;
      DOS.$("mRing").innerHTML = DOS.ring(done / all.length, "var(--brand)", 180, `${done} of ${all.length}`);
      DOS.$("mCounts").innerHTML = ["p", "r", "d", "w", "x"].map((k) => `<div><b>${c[k]}</b><span>${LBL[k]}</span></div>`).join("");
    };
    const set = (id, s) => { S[id] = s; const t = DOS.$("mt-" + id); if (t) t.className = s; const c = DOS.$("ag-" + id);
      if (c) { c.classList.remove("s-running", "s-done", "s-wait", "s-bad"); c.classList.add({ p: "s-running", r: "s-running", d: "s-done", w: "s-wait", x: "s-bad" }[s] || "x");
        const b = c.querySelector(".bar"); if (b) b.style.width = { q: "0", p: "35%", r: "70%", d: "100%", w: "100%", x: "100%" }[s]; const st = c.querySelector(".state"); if (st) st.className = "state " + (s === "r" || s === "p" ? "running" : s === "d" ? "live" : ""); } draw(); };
    const feed = (txt, kind = "") => { const f = DOS.$("mFeed"); if (!f) return; f.insertAdjacentHTML("afterbegin", `<div class="ev new k-${kind}"><span class="dot"></span><span>${esc(txt)}</span></div>`); while (f.children.length > 30) f.lastChild.remove(); };
    draw();
    const names = Object.fromEntries(all.map((a) => [a.id, a.name]));
    let summary = null;
    const total = { agents: 0, live: 0, completed: 0, waiting_approval: 0, failed: 0, blocked: 0, simulated: 0 };
    // One request per domain: each stays well inside Cloud Run's request time limit, and a slow domain never stops the others.
    const doms = vertical === "all" ? ST.data.domains.map((g) => g.vertical) : [vertical];
    try {
      for (const dom of doms) {
      feed(`${dom}: starting`, "agent");
      await DOS.stream(run ? "/api/app/sweep" : "/api/app/prepare", { vertical: dom }, (ev) => {
        if (ev.type === "agent") { set(ev.agent, "p"); feed(`${ev.name}: started (${ev.index}/${ev.total})`, "agent"); }
        if (ev.type === "stage") {
          if (ev.status === "blocked" || ev.status === "failed") { set(ev.agent, "x"); feed(`${names[ev.agent]}: ${ev.stage} ${ev.status}: ${ev.detail}`, "bad"); }
          else if (ev.stage === "run" && ev.status === "running") set(ev.agent, "r");
          else if (!run && ev.stage === "eval" && ev.status === "done") { set(ev.agent, "d"); feed(`${names[ev.agent]}: live`, "ok"); }
        }
        if (ev.type === "run") { const s = ev.run.status; set(ev.agent, s === "completed" ? "d" : s === "waiting_approval" ? "w" : "x");
          feed(`${names[ev.agent]}: ${s === "completed" ? "done" : s === "waiting_approval" ? "waiting for a person" : s}${ev.run.simulated ? " (simulated)" : ""}`, s === "completed" ? "ok" : s === "waiting_approval" ? "warn" : "bad"); }
        if (ev.type === "done") Object.keys(total).forEach((k) => (total[k] += ev.summary[k] || 0));
      });
      }
      summary = total;
    } catch (e) { DOS.toast(e.message, "bad"); }
    clearInterval(clock);
    if (summary) {
      DOS.confetti(innerWidth / 2, 200, 60);
      DOS.toast(run ? `Finished: ${summary.completed} done, ${summary.waiting_approval} waiting for people, ${summary.failed + summary.blocked} stopped.` : `${summary.live} agents live.`, "ok");
      feed(run ? `All finished. Open Approvals to decide the ${summary.waiting_approval} waiting action(s).` : "All agents prepared.", "ok");
      const n = await DOS.api("/api/app/studio"); ST.data = n; DOS.refreshMe();
      DOS.$("mission").querySelector("h3").innerHTML = `Mission Control · finished ${esc(what)} ${run && summary.waiting_approval ? `<button class="btn sm primary" onclick="DOS.go('approvals')" style="margin-left:10px">Open approvals</button>` : ""}`;
    }
  }
})();
