/* Plant floor: every machine live (refreshed every 2 seconds), each breakdown as it is detected, diagnosed and
   dispatched by the six-agent chain (MachineWatch, RootCauseIQ, FixDispatch, SpareSense, PlanSync, LotTrace). */
"use strict";
(() => {
  const { esc, icon, num } = DOS;
  const SIG = { vibration: ["mm/s", "#60a5fa"], temperature: ["°C", "#f87171"], current: ["A", "#fbbf24"], cycle_time: ["s", "#a78bfa"], pressure: ["bar", "#34d399"] };
  const CHAIN = ["MachineWatch", "RootCauseIQ", "FixDispatch", "SpareSense", "PlanSync", "LotTrace"];

  DOS.pages.plant = {
    title: "Plant floor",
    async render(el) {
      el.innerHTML = DOS.skeleton(4);
      const canSim = DOS.can("plant.simulate");
      let st = await DOS.api("/api/plant/state");
      const studio = DOS.S.me.layers || DOS.can("agent.deploy") ? await DOS.api("/api/app/studio") : null;
      const mfg = studio ? (studio.domains.find((d) => d.vertical === "Manufacturing") || { agents: [] }).agents : [];
      const chainLive = mfg.filter((a) => ["machinewatch", "rootcauseiq", "fixdispatch", "sparesense", "plansync", "lottrace"].includes(a.id) && a.state === "live").length;
      el.innerHTML = DOS.header("Manufacturing · live", "Plant floor", "Machines stream readings every 2 seconds. When a reading stays beyond its limit, DOS raises the alarm and six agents respond: watch, diagnose, dispatch, spare part, re-plan, contain suspect lots.",
        canSim ? `<select class="in" id="fm" style="width:auto"></select><select class="in" id="ff" style="width:auto"></select><button class="btn bad" id="fGo">${icon("bolt")}Simulate a fault</button>` : "") + `
        ${studio && chainLive < 6 ? `<div class="card rise" style="margin-bottom:14px;border-color:rgba(251,191,36,.45)"><div class="row"><span class="ico" style="--ic:var(--warn)">${icon("alert")}</span>
          <div class="grow"><b>${chainLive} of 6 response agents are live.</b><div class="small muted">Prepare them once so a breakdown is handled end to end.</div></div><button class="btn primary" id="prepChain">${icon("flag")}Prepare the response agents</button></div></div>` : ""}
        <div class="tiles" id="pk" style="margin-bottom:16px"></div>
        <div class="split"><div><div class="mgrid" id="mg"></div></div><div class="grid" id="inc"></div></div>`;
      if (canSim) {
        DOS.$("fm").innerHTML = st.machines.map((m) => `<option value="${esc(m.machine_id)}" data-type="${esc(m.type)}">${esc(m.machine_id)} · ${esc(m.name)}</option>`).join("");
        const faults = () => { const t = DOS.qs("#fm option:checked").dataset.type; DOS.$("ff").innerHTML = Object.entries(st.faults).filter(([, f]) => f.types.includes(t)).map(([k, f]) => `<option value="${esc(k)}">${esc(f.label)}</option>`).join(""); };
        DOS.$("fm").onchange = faults; faults();
        DOS.$("fGo").onclick = async () => {
          try { const r = await DOS.api("/api/plant/faults", { method: "POST", body: { machine: DOS.$("fm").value, fault: DOS.$("ff").value } }); DOS.toast(r.note, "ok"); }
          catch (e) { DOS.toast(e.message, "bad"); }
        };
      }
      if (DOS.$("prepChain")) DOS.$("prepChain").onclick = async () => {
        const b = DOS.$("prepChain"); b.disabled = true; b.innerHTML = `<span class="spinner"></span>Preparing`;
        let live = 0;
        await DOS.stream("/api/app/prepare", { vertical: "Manufacturing" }, (ev) => { if (ev.type === "stage" && ev.stage === "eval" && ev.status === "done") { live++; b.innerHTML = `<span class="spinner"></span>${live} live`; } });
        DOS.toast("Manufacturing agents are live. Simulate a fault to see the chain respond.", "ok"); DOS.route();
      };
      const draw = () => { kpis(st); machines(st, canSim); incidents(st); };
      draw();
      DOS.every(2000, async () => { try { st = await DOS.api("/api/plant/state"); draw(); } catch { /* keep the last picture */ } });
    },
  };

  function kpis(st) {
    const k = st.kpis;
    DOS.$("pk").innerHTML = [["Running", `${k.running} / ${k.machines}`, "machines healthy", "factory", "var(--ok)"], ["Need attention", k.attention, "warning, alarm or repair", "alert", "var(--warn)"],
      ["Open breakdowns", k.open_incidents, "being handled now", "bolt", "var(--bad)"], ["Minutes to technician", k.avg_min_to_technician ?? "–", "alarm to work order", "clock", "var(--brand)"],
      ["Downtime cost", DOS.inr(k.downtime_cost_inr), `at ${DOS.inr(k.cost_per_hour_inr)} per hour`, "alert", "var(--accent)"]]
      .map(([a, v, h, ic, c]) => `<div class="tile" style="--tc:${c}"><div class="k">${icon(ic)}${a}</div><div class="v">${esc(v)}</div><div class="h">${h}</div></div>`).join("");
  }

  function machines(st, canSim) {
    DOS.$("mg").innerHTML = st.machines.map((m) => {
      const sigs = Object.keys(m.baseline);
      return `<div class="machine ${esc(m.status)}"><div class="row"><b>${esc(m.machine_id)}</b>${DOS.status(m.status === "running" ? "running_m" : m.status)}<span class="small muted right">${esc(m.line)}</span></div>
        <div class="small muted">${esc(m.name)}</div>
        ${sigs.map((s) => { const vals = m.recent.map((r) => r[s]); const lim = (m.limits[s] || [])[1]; const bad = m.alarm_signals.includes(s), warn = m.warning_signals.includes(s);
          return `<div class="sig"><span class="${bad ? "" : "muted"}" style="${bad ? "color:var(--bad)" : warn ? "color:var(--warn)" : ""}">${esc(DOS.title(s))}</span>${DOS.spark(vals, bad ? "var(--bad)" : warn ? "var(--warn)" : (SIG[s] || [])[1], lim)}<b>${num(m.latest[s])} <span class="muted small">${esc((SIG[s] || [""])[0])}</span></b></div>`; }).join("")}
        ${canSim && m.simulated_fault ? `<div class="row small" style="margin-top:8px"><span class="chip warn">Simulated: ${esc(m.simulated_fault)}</span><button class="btn sm right" data-clear="${esc(m.machine_id)}">Reset</button></div>` : ""}</div>`;
    }).join("");
    DOS.qsa("[data-clear]").forEach((b) => (b.onclick = async () => { await DOS.api(`/api/plant/clear/${encodeURIComponent(b.dataset.clear)}`, { method: "POST" }); DOS.toast("Machine reset.", "ok"); }));
  }

  function incidents(st) {
    const open = st.incidents.filter((i) => i.status !== "resolved"), done = st.incidents.filter((i) => i.status === "resolved").slice(0, 3);
    const box = DOS.$("inc");
    const sig = JSON.stringify(st.incidents.map((i) => [i.id, i.status, i.timeline.length, (i.runs || []).map((r) => r.status).join()]));
    if (box.dataset.sig === sig) return; box.dataset.sig = sig;
    box.innerHTML = (open.length ? open : []).map((i) => {
      const done6 = (i.runs || []).map((r) => r.agent);
      return `<div class="card rise" style="border-color:rgba(248,113,113,.45)"><div class="row"><span class="ico" style="--ic:var(--bad)">${icon("alert")}</span><div class="grow"><b>${esc(i.machine_name)}</b><div class="small muted">${esc(i.signal)} ${num(i.value)} ${esc(i.unit)} · limit ${num(i.limit)} · ${DOS.ago(i.detected_at)}</div></div>${DOS.status(i.status)}</div>
        <div class="row" style="gap:6px;margin:12px 0">${CHAIN.map((n) => { const r = (i.runs || []).find((x) => x.agent === n); return `<span class="chip ${r ? (r.status === "completed" ? "ok" : r.status === "waiting_approval" ? "warn" : r.status === "failed" ? "bad" : "info") : ""}">${r ? (r.status === "completed" ? "✓ " : r.status === "waiting_approval" ? "⏳ " : "") : ""}${n}</span>`; }).join("")}</div>
        ${i.root_cause ? `<div class="small" style="margin-bottom:8px"><b>Likely cause:</b> ${esc(DOS.title(i.root_cause))} ${i.confidence ? `(${DOS.pct(i.confidence)})` : ""} ${i.technician ? `· <b>Technician:</b> ${esc(i.technician)}` : ""} ${i.part ? `· <b>Part:</b> ${esc(i.part)}` : ""}</div>` : ""}
        <div class="tl">${i.timeline.slice(-8).map((t, k) => `<div style="animation-delay:${k * 30}ms"><b>${esc(t.who)}</b> <span>${new Date(t.at * 1000).toLocaleTimeString()}</span><br>${esc(t.what)}</div>`).join("")}</div>
        ${(i.runs || []).some((r) => r.status === "waiting_approval") ? `<button class="btn sm primary" style="margin-top:8px" onclick="DOS.go('approvals')">Approvals waiting</button>` : ""}${done6.length ? "" : ""}</div>`;
    }).join("") + (open.length ? "" : `<div class="card rise center"><span class="ico" style="margin:0 auto 10px;width:46px;height:46px;--ic:var(--ok)">${icon("check")}</span><h3>All machines healthy</h3><p class="muted small">${DOS.can("plant.simulate") ? "Simulate a fault above. Signals drift for about 30 seconds before DOS confirms the alarm." : "Breakdowns appear here the moment DOS detects them."}</p></div>`)
      + done.map((i) => `<div class="item"><span class="ico" style="--ic:var(--ok)">${icon("check")}</span><div class="grow"><b>${esc(i.machine_name)}</b><div class="small muted">Resolved in ${num(i.minutes_to_resolve)} min · ${esc(DOS.title(i.root_cause || ""))}</div></div></div>`).join("");
  }
})();
