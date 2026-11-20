/* Live runs: every agent run, refreshing by itself, and the full trace of one run, coloured by layer. */
"use strict";
(() => {
  const { esc, icon, num } = DOS;
  const F = { status: "" };

  DOS.pages.runs = {
    title: "Live runs",
    async render(el, arg) { if (arg) return detail(el, arg); return list(el); },
  };

  async function list(el) {
    el.innerHTML = DOS.header("Layer 4 · AI agents at work", "Live runs", "Every run of every agent, newest first. This page refreshes itself; click a run to see each step it took and which layer took it.",
      `<div class="seg" id="rf">${[["", "All"], ["running", "Working"], ["waiting_approval", "Waiting"], ["completed", "Done"], ["failed", "Failed"]].map(([v, l]) => `<button data-v="${v}" class="${F.status === v ? "on" : ""}">${l}</button>`).join("")}</div>`) +
      `<div class="tw rise"><table><thead><tr><th>Agent</th><th>Status</th><th>Engine</th><th>Started</th><th>Time</th><th>Steps</th><th>Cost</th><th>Answer</th></tr></thead><tbody id="rb"><tr><td colspan="8"><div class="skel"></div></td></tr></tbody></table></div>`;
    DOS.qsa("#rf button").forEach((b) => (b.onclick = () => { F.status = b.dataset.v; DOS.qsa("#rf button").forEach((x) => x.classList.toggle("on", x === b)); load(true); }));
    const seen = new Set();
    async function load(reset) {
      const rows = await DOS.api(`/api/runs?limit=120${F.status ? "&status=" + F.status : ""}`);
      const tb = DOS.$("rb"); if (!tb) return;
      if (reset) seen.clear();
      tb.innerHTML = rows.length ? rows.map((r) => `<tr class="click ${seen.size && !seen.has(r.id) ? "new" : ""}" data-id="${esc(r.id)}"><td><div class="row" style="gap:8px;flex-wrap:nowrap">${DOS.domIcon(r.vertical)}<b>${esc(r.agent_name)}</b></div></td>
        <td>${DOS.status(r.status)}</td><td>${DOS.simChip(r.simulated)}</td><td class="muted">${DOS.ago(r.created_at)}</td><td>${num(r.latency_ms)} ms</td><td>${num((r.model_calls || 0) + (r.tool_calls || 0))}</td>
        <td>${DOS.inr(r.cost_inr)}</td><td class="muted" style="max-width:360px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(r.output || r.error || "")}</td></tr>`).join("")
        : `<tr><td colspan="8" class="empty">No runs yet. Launch an agent from Agent Studio.</td></tr>`;
      rows.forEach((r) => seen.add(r.id));
      DOS.qsa("tr.click", tb).forEach((tr) => (tr.onclick = () => DOS.go("runs/" + tr.dataset.id)));
    }
    await load(true);
    DOS.every(3000, () => load(false));
  }

  async function detail(el, id) {
    el.innerHTML = DOS.skeleton(4);
    let r = await DOS.api(`/api/runs/${encodeURIComponent(id)}`);
    const draw = () => {
      const byLayer = [2, 3, 4, 5].map((n) => r.steps.filter((s) => s.layer === n).length);
      el.innerHTML = DOS.header(`<a href="#runs" style="text-decoration:none">← Live runs</a>`, `${esc(r.agent_name)}`, `${esc(r.client_name || "")} · version ${esc(r.version)} · rules version ${esc(r.config_version)} · started by ${esc(r.user)} ${DOS.ago(r.created_at)}`,
        `${DOS.status(r.status)}${DOS.simChip(r.simulated)}`) + `
        <div class="tiles" style="margin-bottom:16px">${DOS.tile("Time", r.latency_ms, "milliseconds", "clock", "var(--brand)", 0)}${DOS.tile(r.simulated ? "Model calls (simulated)" : "Gemini calls", r.model_calls, `${num(r.input_tokens)} in / ${num(r.output_tokens)} out tokens`, "model", "var(--l4)", 1)}
          ${DOS.tile("Tool calls", r.tool_calls, "real tools on company data", "tool", "var(--l4)", 2)}${DOS.tile("Rule reads", byLayer[0], "layer 2, read at the moment of use", "rules", "var(--l2)", 3)}
          ${DOS.tile("Data reads", byLayer[1], "layer 3, every read logged", "db", "var(--l3)", 4)}${DOS.tile("Safety checks", byLayer[3], "layer 5 guardrails and approvals", "shield", "var(--l5)", 5)}</div>
        <div class="split"><div class="card rise"><h3>Every step, in order</h3><p class="small muted" style="margin:4px 0 12px">Each line is tagged with the layer that produced it.</p><div class="trace" style="max-height:none">${r.steps.map((s, i) => DOS.stepRow(s, i)).join("")}</div></div>
          <div class="grid"><div class="card rise" style="--i:1"><h3>Request</h3><pre style="margin-top:8px">${esc(r.input)}</pre></div>
            <div class="card rise" style="--i:2"><h3>Answer</h3><div class="answer ${r.status === "completed" ? "" : r.status === "waiting_approval" ? "wait" : "bad"}" style="margin-top:8px">${esc(r.output || r.error || "No answer yet.")}</div></div>
            ${r.approvals.length ? `<div class="card rise" style="--i:3"><h3>Decisions</h3><div class="list" style="margin-top:8px">${r.approvals.map((a) => `<div class="item">${DOS.status(a.status)}<div class="grow"><b>${esc(DOS.title(a.tool))}</b><div class="small muted">${esc(a.decided_by ? "by " + a.decided_by : a.why || "")}</div></div>
              ${a.status === "pending" && DOS.can("approval.decide") ? `<button class="btn sm good" data-ok="${esc(a.id)}">Approve</button><button class="btn sm bad" data-no="${esc(a.id)}">Reject</button>` : ""}</div>`).join("")}</div></div>` : ""}
            ${r.actions.length ? `<div class="card rise" style="--i:4"><h3>What the agent did</h3><div class="list" style="margin-top:8px">${r.actions.map((a) => `<div class="item"><span class="ico" style="--ic:var(--ok)">${icon("bolt")}</span><div class="grow"><b>${esc(DOS.title(a.kind || a.tool || "action"))}</b><div class="small muted">${esc(a.summary || JSON.stringify(a.payload || a.args || {}).slice(0, 160))}</div></div></div>`).join("")}</div></div>` : ""}
          </div></div>`;
      DOS.countUp(el);
      DOS.qsa("[data-ok],[data-no]", el).forEach((b) => (b.onclick = async () => {
        try { await DOS.api(`/api/approvals/${encodeURIComponent(b.dataset.ok || b.dataset.no)}/decision`, { method: "POST", body: { approved: !!b.dataset.ok, note: "Decided on the run page" } });
          DOS.toast("Decision recorded. The agent continues.", "ok"); DOS.refreshMe(); } catch (e) { DOS.toast(e.message, "bad"); }
      }));
    };
    draw();
    DOS.every(2000, async () => { const n = await DOS.api(`/api/runs/${encodeURIComponent(id)}`); if (n.steps.length !== r.steps.length || n.status !== r.status) { r = n; draw(); } });
  }
})();
