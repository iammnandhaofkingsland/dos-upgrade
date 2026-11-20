/* The five DOS layers, for the Business Owner and the Operations Manager only.
   The five layers: overview and "follow one run through the layers". Layer 2: rules and limits.
   Layer 3: data sources and every read. Layer 4: agent versions and their evaluation scores. */
"use strict";
(() => {
  const { esc, icon, num } = DOS;
  const LNAME = { 1: "Experience", 2: "Client configuration", 3: "Data", 4: "AI agents", 5: "Safety, security and governance" };

  /* ---------------------------------------------------------------- the five layers */
  DOS.pages.layers = {
    title: "The five layers",
    async render(el) {
      el.innerHTML = DOS.skeleton(5);
      const [L, runs] = await Promise.all([DOS.api("/api/app/layers"), DOS.api("/api/runs?limit=30")]);
      el.innerHTML = DOS.header("DOS under the hood", "Five layers, one platform", `Your team works in layer 1. Rules, data, agents and safety underneath make every action safe, explainable and specific to ${esc(L.client)}. Click a layer to open it.`) + `
        <div class="stack">${L.layers.map((l, i) => `<div class="lay rise" style="--i:${i};--lc:var(--l${l.n})" data-p="${esc(l.page)}"><div class="num">L${l.n}</div>
          <div><h3>${esc(l.name)}</h3><div class="what">${esc(l.what)}</div><ul>${l.facts.map((f) => `<li>${esc(f)}</li>`).join("")}</ul></div>
          <div style="text-align:right"><span class="chip dot ${l.status === "ok" ? "ok" : l.status === "stop" ? "bad" : "warn"}">${l.status === "ok" ? "Healthy" : l.status === "stop" ? "Stopped" : "Check"}</span>
            <div class="small muted" style="margin-top:8px">${num(l.trace_steps)} trace steps in 24 h</div></div></div>`).join("")}</div>
        <h2>Follow one run through the layers</h2>
        <div class="card rise"><div class="row"><select class="in" id="pick" style="max-width:420px">${runs.length ? runs.map((r) => `<option value="${esc(r.id)}">${esc(r.agent_name)} · ${esc(DOS.title(r.status))} · ${DOS.ago(r.created_at)}</option>`).join("") : `<option value="">No runs yet: launch an agent first</option>`}</select>
          <span class="small muted">Every step of the run, grouped by the layer that took it.</span></div><div id="follow" style="margin-top:14px"></div></div>`;
      DOS.qsa(".lay").forEach((d) => (d.onclick = () => DOS.go(d.dataset.p)));
      const follow = async () => {
        const id = DOS.$("pick").value; if (!id) return;
        const r = await DOS.api(`/api/runs/${encodeURIComponent(id)}`);
        DOS.$("follow").innerHTML = `<div class="flowlayers">${[1, 2, 3, 4, 5].map((n) => { const st = r.steps.filter((s) => s.layer === n); const first = st.slice(0, 3);
          return `<div class="rise" style="--i:${n};--lc:var(--l${n})"><span class="lt L${n}">L${n}</span><b>${n === 1 ? 1 : st.length}</b><div class="small" style="color:var(--text2)">${esc(LNAME[n])}</div>
            <div class="small muted" style="margin-top:6px">${n === 1 ? `Started by ${esc(r.user)} in the DOS app` : first.map((s) => esc(DOS.title(s.name))).join(" · ") || "Not needed in this run"}</div></div>`; }).join("")}</div>
          <div class="trace" style="margin-top:12px;max-height:360px">${r.steps.map((s, i) => DOS.stepRow(s, i)).join("")}</div>`;
      };
      if (runs.length) { DOS.$("pick").onchange = follow; follow(); }
    },
  };

  /* ---------------------------------------------------------------- layer 2: rules and limits */
  DOS.pages.rules = {
    title: "Rules & limits",
    async render(el) {
      el.innerHTML = DOS.skeleton(4);
      const [c, versions] = await Promise.all([DOS.api("/api/client"), DOS.api("/api/client/versions")]);
      const edit = DOS.can("config.edit");
      const groups = {}; c.schema.forEach((p) => (groups[p.group] = groups[p.group] || []).push(p));
      const show = (p, v) => p.type === "bool" ? (v ? "Yes" : "No") : Array.isArray(v) ? v.join(", ") || "none" : (v === "" ? "not set" : `${v}${p.unit ? " " + p.unit : ""}`);
      el.innerHTML = DOS.header(`${DOS.lt(2)} Layer 2 · client configuration`, "Rules & limits", `${esc(c.client.name)}'s rules, version ${c.client.version}. Agents read these at the moment they act, so a change applies to the very next run, with no code. ${edit ? "Click a value to change it." : "Only the Business Owner can change them."}`) + `
        <div class="split"><div class="grid">${Object.entries(groups).map(([g, ps], gi) => `<div class="card rise" style="--i:${gi}"><h3>${esc(DOS.title(g))}</h3><div class="tw" style="margin-top:10px"><table><tbody>
          ${ps.map((p) => { const v = c.effective[p.key], changed = JSON.stringify(v) !== JSON.stringify(p.default);
            return `<tr class="${edit && !p.locked ? "click" : ""}" data-k="${esc(p.key)}"><td style="width:46%"><b>${esc(p.label)}</b>${p.help ? `<div class="small muted">${esc(p.help)}</div>` : ""}</td>
              <td>${esc(show(p, v))} ${changed ? `<span class="chip info">tuned</span>` : ""}${p.locked ? ` <span class="chip">${icon("lock")}locked</span>` : ""}</td><td class="small muted">${esc(p.enforced)}</td></tr>`; }).join("")}
          </tbody></table></div></div>`).join("")}</div>
          <div class="card rise" style="position:sticky;top:80px"><h3>Change history</h3><p class="small muted">Every change is a new version, recorded with who and why.</p>
            <div class="tl" style="margin-top:10px">${versions.slice(0, 12).map((v) => `<div><b>Version ${v.version}</b> <span>${DOS.ago(v.created_at)} · ${esc(v.actor)}</span><br>${esc(v.note || "")}
              <span>${(v.diff || []).slice(0, 3).map((d) => esc(`${d.key || d.field}: ${JSON.stringify(d.old ?? d.before)} → ${JSON.stringify(d.new ?? d.after)}`)).join("<br>")}</span></div>`).join("") || "<div>No changes yet</div>"}</div></div></div>`;
      if (!edit) return;
      DOS.qsa("tr.click", el).forEach((tr) => (tr.onclick = () => {
        const p = c.schema.find((x) => x.key === tr.dataset.k), v = c.effective[p.key];
        const input = p.type === "bool" ? `<select class="in" id="sv"><option value="true" ${v ? "selected" : ""}>Yes</option><option value="false" ${!v ? "selected" : ""}>No</option></select>`
          : p.type === "choice" ? `<select class="in" id="sv">${p.choices.map((x) => `<option ${x === v ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>`
          : `<input class="in" id="sv" value="${esc(Array.isArray(v) ? v.join(", ") : v)}">${p.min != null ? `<div class="small muted" style="margin-top:4px">Allowed ${p.min} to ${p.max} ${esc(p.unit)}</div>` : ""}`;
        DOS.modal(`<h3>${esc(p.label)}</h3><p class="muted">${esc(p.help || "")}</p><label class="f" style="margin-top:12px">New value${input}</label>
          <label class="f" style="margin-top:10px">Why (recorded in the audit trail)<input class="in" id="sn" placeholder="e.g. festive season limit"></label>
          <div class="acts"><button class="btn" data-close>Cancel</button><button class="btn primary" id="sGo">Save as a new version</button></div>`, (sc, close) => {
          DOS.qs("#sGo", sc).onclick = async () => {
            let val = DOS.qs("#sv", sc).value;
            if (p.type === "bool") val = val === "true"; else if (p.type === "list") val = val.split(",").map((x) => x.trim()).filter(Boolean); else if (p.type === "int" || p.type === "float") val = +val;
            try { const r = await DOS.api("/api/client", { method: "PUT", body: { policies: { [p.key]: val }, note: DOS.qs("#sn", sc).value || "changed in the DOS app" } });
              close(); DOS.toast(`Saved as version ${r.client.version}. The next run uses it.`, "ok"); DOS.route(); } catch (e) { DOS.toast(e.message, "bad"); }
          };
        });
      }));
    },
  };

  /* ---------------------------------------------------------------- layer 3: data */
  DOS.pages.data = {
    title: "Data & access",
    async render(el) {
      el.innerHTML = DOS.skeleton(4);
      const [inv, acc] = await Promise.all([DOS.api("/api/data"), DOS.api("/api/data/access?limit=60")]);
      const manage = DOS.can("data.manage");
      const cls = { Restricted: "bad", Confidential: "warn", Internal: "info", Public: "ok" };
      el.innerHTML = DOS.header(`${DOS.lt(3)} Layer 3 · data`, "Data & access", "Every source an agent may read, its classification, which agents use it, and every single read. Personal fields are masked by role; nothing reaches an agent except through this gate.") + `
        <div class="tiles" style="margin-bottom:16px">${DOS.tile("Sources connected", inv.filter((d) => d.status !== "none").length, `of ${inv.length} relevant to this company`, "db", "var(--l3)", 0)}
          ${DOS.tile("Reads logged", acc.length, "latest 60 shown below", "eye", "var(--brand)", 1)}${DOS.tile("Restricted sources", inv.filter((d) => d.classification === "Restricted").length, "personal or financial data", "lock", "var(--bad)", 2)}
          ${DOS.tile("Reads refused", acc.filter((a) => a.status === "denied").length, "blocked by the gate", "shield", "var(--l5)", 3)}</div>
        <div class="tw rise"><table><thead><tr><th>Source</th><th>Class</th><th>Status</th><th>Rows</th><th>Used by</th><th>Reads</th>${manage ? "<th></th>" : ""}</tr></thead><tbody>
          ${inv.map((d) => `<tr><td><b>${esc(d.title)}</b><div class="small muted">${esc(d.connector)}${d.personal_fields.length ? " · personal: " + esc(d.personal_fields.join(", ")) : ""}</div></td>
            <td><span class="chip ${cls[d.classification] || ""}">${esc(d.classification)}</span></td><td>${d.status === "none" ? `<span class="chip">Not connected</span>` : `<span class="chip ok dot">${esc(DOS.title(d.status))}</span>`}</td>
            <td>${num(d.rows)}</td><td class="small muted">${esc(d.agents.slice(0, 4).join(", "))}${d.agents.length > 4 ? ` +${d.agents.length - 4}` : ""}</td><td>${num(d.reads)}</td>
            ${manage ? `<td><span class="toggle ${d.status !== "none" ? "on" : ""}" data-n="${esc(d.name)}" data-on="${d.status !== "none"}" title="Connect the sample data"></span></td>` : ""}</tr>`).join("")}</tbody></table></div>
        <h2>Every read, newest first</h2>
        <div class="tw rise"><table><thead><tr><th>When</th><th>Source</th><th>Agent</th><th>Rows</th><th>Personal data</th><th>Result</th></tr></thead><tbody>
          ${acc.map((a) => `<tr><td class="muted">${DOS.ago(a.created_at)}</td><td>${esc(a.title)}</td><td>${esc(a.agent_name || "platform")}</td><td>${num(a.rows)}</td><td>${a.personal_data ? `<span class="chip warn">masked by role</span>` : "–"}</td><td>${DOS.status(a.status === "read" ? "completed" : "failed")}</td></tr>`).join("") || `<tr><td colspan="6" class="empty">No reads yet</td></tr>`}</tbody></table></div>`;
      DOS.countUp(el);
      DOS.qsa(".toggle[data-n]").forEach((t) => (t.onclick = async () => {
        try { await DOS.api(`/api/data/${encodeURIComponent(t.dataset.n)}/connect`, { method: "POST", body: { mode: t.dataset.on === "true" ? "none" : "sample" } }); t.classList.toggle("on"); DOS.toast("Data connection changed and recorded.", "ok"); setTimeout(DOS.route, 400); }
        catch (e) { DOS.toast(e.message, "bad"); }
      }));
    },
  };

  /* ---------------------------------------------------------------- layer 4: versions */
  DOS.pages.versions = {
    title: "Agent versions",
    async render(el) {
      el.innerHTML = DOS.skeleton(3);
      const rows = await DOS.api("/api/app/versions");
      el.innerHTML = DOS.header(`${DOS.lt(4)} Layer 4 · AI agents`, "Agent versions", "No version goes live without passing the governance gate and its own evaluation. Each line is one attempt, with its score and how it was checked.",
        `<button class="btn" onclick="DOS.go('studio')">${icon("bot")}Agent Studio</button>`) + `
        <div class="tw rise"><table><thead><tr><th>Agent</th><th>Version</th><th>Status</th><th>Evaluation</th><th>Checked with</th><th>Risk</th><th>Rules version</th><th>By</th><th>When</th></tr></thead><tbody>
        ${rows.map((d) => `<tr><td><div class="row" style="gap:8px;flex-wrap:nowrap">${DOS.domIcon(d.vertical)}<b>${esc(d.name)}</b></div></td><td>v${esc(d.version)}</td><td>${DOS.status(d.status === "live" ? "live" : d.status === "superseded" ? "closed" : d.status === "blocked" || d.status === "failed" ? "failed" : d.status)}</td>
          <td>${d.score != null ? `<div class="row" style="gap:8px;flex-wrap:nowrap"><div class="meter" style="width:80px"><i style="width:${d.score * 100}%"></i></div>${DOS.pct(d.score)}</div>` : "–"}</td>
          <td>${d.mode === "mock" ? `<span class="chip warn">Simulated checks</span>` : `<span class="chip violet">Gemini judge</span>`}</td><td>${d.risk ? DOS.status(d.risk) : "–"}</td><td>v${esc(d.config_version)}</td><td class="small">${esc(d.created_by)}</td><td class="muted">${DOS.ago(d.created_at)}</td></tr>`).join("")
          || `<tr><td colspan="9" class="empty">No versions yet. Prepare or launch an agent in Agent Studio.</td></tr>`}</tbody></table></div>`;
    },
  };
})();
