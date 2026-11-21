/* Gold data (layer 3, Business Owner and Operations Manager only): for any agent, the data its tools read,
   as a bronze -> silver -> gold pipeline, with the gold rows shown and every personal value masked. */
"use strict";
(() => {
  const { esc, icon, num } = DOS;
  const CLS = { Restricted: "bad", Confidential: "warn", Internal: "info", Public: "ok" };

  DOS.pages.gold = {
    title: "Gold data",
    async render(el, arg) {
      el.innerHTML = DOS.skeleton(4);
      const o = await DOS.api("/api/app/gold");
      const pick = arg || (o.agents.find((a) => a.personal_data) || o.agents[0] || {}).id;
      el.innerHTML = DOS.header(`${DOS.lt(3)} Layer 3 · data`, "Gold data each agent reads",
        "Pick an agent to see the exact data its tools read through the data gate: where it comes from (bronze), how it is checked (silver), and the agent-ready rows (gold). Personal values are masked for every role, and opening this view is recorded in the audit trail.") +
        `<div class="split gsplit"><div class="card rise gpick"><input class="in" id="gq" placeholder="Search agents or data"><div id="glist" class="glist"></div></div><div id="gbody">${DOS.skeleton(3)}</div></div>`;
      const list = () => {
        const q = DOS.$("gq").value.toLowerCase();
        DOS.$("glist").innerHTML = o.verticals.map((v) => { const rows = o.agents.filter((a) => a.vertical === v && (!q || (a.name + a.titles.join(" ")).toLowerCase().includes(q)));
          return rows.length ? `<div class="small muted gv">${esc(v)}</div>` + rows.map((a) => `<button class="gitem ${a.id === pick ? "on" : ""}" data-a="${esc(a.id)}"><b>${esc(a.name)}</b>
            <span>${a.personal_data ? `${icon("lock")}` : ""}<span class="chip ${CLS[a.classification] || ""}">${esc(a.classification)}</span></span></button>`).join("") : ""; }).join("");
        DOS.qsa(".gitem").forEach((b) => (b.onclick = () => DOS.go("gold/" + b.dataset.a)));
      };
      DOS.$("gq").oninput = list; list();
      if (pick) show(pick);
    },
  };

  async function show(id) {
    const g = await DOS.api(`/api/app/gold/${encodeURIComponent(id)}`), box = DOS.$("gbody"); if (!box) return;
    const lr = g.last_run;
    box.innerHTML = `<div class="card rise"><div class="row"><span class="ico">${icon("db")}</span><div class="grow"><h3 style="margin:0">${esc(g.agent.name)}</h3>
        <div class="small muted">${esc(g.agent.vertical)} · reads ${g.datasets.length} data source${g.datasets.length === 1 ? "" : "s"} through ${g.agent.tools.length} tools</div></div>
        <span class="chip ${CLS[g.lineage.max_classification] || ""}">Highest: ${esc(g.lineage.max_classification)}</span>${g.lineage.personal_data ? `<span class="chip violet">${icon("eye")}PII masked</span>` : ""}</div>
        ${lr ? `<div class="small muted" style="margin-top:10px">Last run ${DOS.ago(lr.created_at)} (${esc(DOS.title(lr.status))}) read: ${lr.reads.map((r) => `<span class="chip" style="margin:2px">${esc(r.title || r.dataset)} · ${num(r.rows || 0)} rows · by ${esc(r.by)}</span>`).join("") || "nothing"}</div>` : `<div class="small muted" style="margin-top:10px">No run yet. Run the agent and its reads appear here.</div>`}</div>
      ${g.datasets.map((d, i) => ds(d, i)).join("") || DOS.empty("db", "No company data", "This agent works only from the request and its policy library.")}`;
  }

  function ds(d, i) {
    if (!d.connected) return `<div class="card rise" style="--i:${i}"><div class="row"><b class="grow">${esc(d.title)}</b><span class="chip bad">Not connected</span></div><p class="small muted">${esc(d.note)}</p></div>`;
    const m = d.medallion;
    return `<div class="card rise" style="--i:${i}">
      <div class="row"><div class="grow"><h3 style="margin:0">${esc(d.title)}</h3><div class="small muted">${esc(d.description)} Owner: ${esc(d.owner)}.</div></div>
        <span class="chip ${CLS[d.classification] || ""}">${esc(d.classification)}</span></div>
      <div class="medal">
        <div class="mb bronze"><span>Bronze · raw</span><b>${num(m.bronze.rows)}</b><small>${esc(m.bronze.source)}</small><small class="muted">Production: ${esc(m.bronze.connector_in_production)}</small></div>
        <div class="mb silver"><span>Silver · validated</span><b>${num(m.silver.rows)}</b><small>${num(m.silver.rejected)} rejected · ${m.silver.completeness}% complete</small><small class="muted">${m.silver.checks.map(esc).join(" · ")}</small></div>
        <div class="mb gold"><span>Gold · agent-ready</span><b>${num(m.gold.rows)}</b><small>${num(m.gold.columns)} columns</small><small class="muted">${esc(m.gold.served_by)}</small></div>
      </div>
      <div class="row small muted" style="margin:6px 0 8px;gap:8px">${d.masked_columns.length ? `${icon("lock")} Masked: ${d.masked_columns.map((c) => `<span class="chip violet">${esc(c)}</span>`).join(" ")}` : `${icon("check")} No personal columns`}
        <span class="grow"></span>${num(d.reads)} agent reads${d.last_read ? ", last " + DOS.ago(d.last_read) : ""}</div>
      <div class="tw"><table><thead><tr>${d.columns.map((c) => `<th class="${d.masked_columns.includes(c) ? "pii" : ""}">${esc(c)}</th>`).join("")}</tr></thead>
        <tbody>${d.rows.map((r) => `<tr>${r.map((v, k) => `<td class="${d.masked_columns.includes(d.columns[k]) ? "pii" : ""}">${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
      <div class="small muted" style="margin-top:6px">Showing ${d.showing} of ${num(d.row_count)} gold rows. ${esc(d.note)}</div></div>`;
  }
})();
