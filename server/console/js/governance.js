/* Layer 5 pages and the live feed.
   Safety: the emergency stop, the safety self-test, incidents and (for the owner and ops manager) the risk register
   and who-may-do-what. Audit & evidence: the hash-chained audit trail, its verification and the evidence pack.
   Live activity: every event as it happens. */
"use strict";
(() => {
  const { esc, icon, num } = DOS;

  /* ---------------------------------------------------------------- safety and governance */
  DOS.pages.safety = {
    title: "Safety & governance",
    async render(el) {
      el.innerHTML = DOS.skeleton(4);
      const full = DOS.S.me.layers;
      const [g, inc] = await Promise.all([full ? DOS.api("/api/governance/overview") : Promise.resolve(null), DOS.api("/api/governance/incidents?status=open")]);
      const kill = DOS.S.me.kill || {};
      el.innerHTML = DOS.header(full ? `${DOS.lt(5)} Layer 5 · safety, security, governance` : "Safety", full ? "Safety & governance" : "Emergency stop",
        full ? "Every action is checked before it happens, risky actions wait for a person, and everything is recorded. Prove it any time with the self-test." : "If agents ever do something unexpected, stop them all with one press. Every agent halts at its next step.") + `
        <div class="grid g2" style="margin-bottom:14px">
          <div class="card rise center" style="padding:26px"><button class="bigstop ${kill.engaged ? "on" : ""}" id="big" ${DOS.can("killswitch") ? "" : "disabled"}>${kill.engaged ? "RELEASE" : "STOP ALL<br>AGENTS"}</button>
            <p style="margin:16px 0 0">${kill.engaged ? `<b style="color:var(--bad)">Engaged</b> by ${esc(kill.by)} ${DOS.ago(kill.at)}: ${esc(kill.reason)}` : `<b style="color:var(--ok)">Clear.</b> Agents act within the company's rules.`}</p></div>
          <div class="card rise" style="--i:1"><div class="row"><h3>Safety self-test</h3>${DOS.can("selftest.run") ? `<button class="btn primary sm right" id="st">${icon("shield")}Run it now</button>` : ""}</div>
            <p class="small muted">DOS attacks its own rules: over-limit refunds, messages at night, hidden instructions in data, an auditor trying to approve. Each probe passes only if DOS refused it.</p><div id="stOut">${g && g.selftest ? selftest(g.selftest) : `<p class="muted small">Not run yet.</p>`}</div></div></div>
        <div class="card rise" style="margin-bottom:14px"><h3>Open incidents · ${inc.length}</h3><div class="list" style="margin-top:10px">${inc.length ? inc.map((x) => `<div class="item"><span class="ico" style="--ic:${x.severity === "high" ? "var(--bad)" : "var(--warn)"}">${icon("alert")}</span>
          <div class="grow"><b>${esc(DOS.title(x.kind))}</b><div class="small muted">${esc(x.summary)} · ${DOS.ago(x.created_at)}</div></div>${DOS.can("incident.close") ? `<button class="btn sm" data-close-inc="${esc(x.id)}">Close</button>` : ""}</div>`).join("") : `<p class="muted">No open incidents.</p>`}</div></div>
        ${full ? `<div class="grid g2"><div class="card rise"><h3>Risk register</h3><p class="small muted">Risk is worked out from what each agent can do and which data it reads, never typed by hand.</p>
            <div class="tw" style="margin-top:10px;max-height:420px"><table><thead><tr><th>Agent</th><th>Risk</th><th>State</th><th>Accepted by</th></tr></thead><tbody>${g.register.map((r) => `<tr><td><b>${esc(r.name)}</b><div class="small muted">${esc(r.factors.slice(0, 2).join("; "))}</div></td><td>${DOS.status(r.tier)}</td><td>${DOS.status(r.state)}</td><td class="small">${esc(r.risk_acceptance ? r.risk_acceptance.by : "–")}</td></tr>`).join("")}</tbody></table></div></div>
          <div class="card rise" style="--i:1"><h3>Who may do what</h3><p class="small muted">Five roles. The server checks every request, whatever the screen shows.</p><div class="tw" style="margin-top:10px"><table><thead><tr><th>Permission</th>${["owner", "operator", "approver", "technician", "auditor"].map((r) => `<th>${esc({ owner: "Owner", operator: "Ops Mgr", approver: "Approver", technician: "Tech", auditor: "Auditor" }[r])}</th>`).join("")}</tr></thead>
            <tbody>${g.matrix.map((m) => `<tr><td class="small">${esc(m.permission)}</td>${["owner", "operator", "approver", "technician", "auditor"].map((r) => `<td>${m[r] ? `<span style="color:var(--ok)">●</span>` : `<span class="muted">·</span>`}</td>`).join("")}</tr>`).join("")}</tbody></table></div></div></div>
          <h2>${num(g.controls.length)} controls, each with where it is enforced</h2><div class="tw rise"><table><thead><tr><th>Control</th><th>Layer</th><th>What it does</th><th>Where</th></tr></thead><tbody>${g.controls.map((c) => `<tr><td><b>${esc(c.name)}</b></td><td>${DOS.lt(c.layer)}</td><td class="small">${esc(c.what)}</td><td class="small muted mono">${esc(c.where)}</td></tr>`).join("")}</tbody></table></div>` : ""}`;
      DOS.$("big").onclick = () => DOS.emergency(!kill.engaged);
      if (DOS.$("st")) DOS.$("st").onclick = async () => {
        const b = DOS.$("st"); b.disabled = true; b.innerHTML = `<span class="spinner"></span>Testing`;
        try { const r = await DOS.api("/api/governance/selftest", { method: "POST" }); DOS.$("stOut").innerHTML = selftest(r); if (r.passed === r.total) DOS.confetti(innerWidth * 0.75, 260, 40); }
        catch (e) { DOS.toast(e.message, "bad"); }
        b.disabled = false; b.innerHTML = `${icon("refresh")}Run again`;
      };
      DOS.qsa("[data-close-inc]").forEach((b) => (b.onclick = async () => {
        await DOS.api(`/api/governance/incidents/${encodeURIComponent(b.dataset.closeInc)}/close`, { method: "POST", body: { note: "Reviewed and closed in the DOS app" } }); DOS.toast("Incident closed.", "ok"); DOS.route();
      }));
    },
  };
  const selftest = (r) => `<div class="row" style="margin:8px 0"><span class="chip ${r.passed === r.total ? "ok" : "bad"} dot">${r.passed} of ${r.total} probes refused</span><span class="small muted">${DOS.ago(r.created_at)} by ${esc(r.ran_by)}</span></div>
    <div class="checks" style="max-height:260px;overflow:auto">${r.results.map((x, i) => `<div style="--i:${i}"><span style="color:${x.passed ? "var(--ok)" : "var(--bad)"}">${x.passed ? "✓" : "✗"}</span><div><b>${esc(x.name)}</b> ${DOS.lt(x.layer)}<div class="small muted">${esc(x.observed)}</div></div></div>`).join("")}</div>`;

  /* ---------------------------------------------------------------- audit and evidence */
  DOS.pages.audit = {
    title: "Audit & evidence",
    async render(el) {
      el.innerHTML = DOS.skeleton(4);
      const [rows, v] = await Promise.all([DOS.api("/api/audit?limit=300"), DOS.api("/api/audit/verify")]);
      el.innerHTML = DOS.header(`${DOS.lt(5)} Governance · proof`, "Audit & evidence", "Every sign-in, run decision, approval, rule change and stop is written to a chain where each record carries the fingerprint of the one before. Change or delete any record and the chain breaks.",
        `<button class="btn" id="ver">${icon("shield")}Verify the chain</button>${DOS.can("evidence.export") ? `<button class="btn primary" id="ev">${icon("download")}Evidence pack</button>` : ""}`) + `
        <div class="card hero rise" style="margin-bottom:14px"><div class="row" style="position:relative;z-index:1"><span class="ico" style="--ic:${v.intact ? "var(--ok)" : "var(--bad)"};width:48px;height:48px">${icon(v.intact ? "check" : "alert")}</span>
          <div><h3 id="vt">${v.intact ? "Chain intact" : "CHAIN BROKEN at record " + esc(v.broken_at_seq)}</h3><div class="small muted">${num(v.records)} records · head ${esc(v.head || "")}</div></div></div></div>
        <div class="tw rise"><table><thead><tr><th>#</th><th>When</th><th>Who</th><th>Role</th><th>Action</th><th>On</th><th>Fingerprint</th></tr></thead><tbody>
          ${rows.map((a) => `<tr><td class="mono">${a.seq}</td><td class="muted">${DOS.ago(a.created_at)}</td><td>${esc(a.actor)}</td><td class="small">${esc(a.role || "")}</td><td><b>${esc(a.action)}</b></td><td class="small">${esc(a.target)}</td><td class="mono small muted">${esc((a.hash || "").slice(0, 12))}</td></tr>`).join("")}</tbody></table></div>`;
      DOS.$("ver").onclick = async () => {
        const b = DOS.$("ver"); b.innerHTML = `<span class="spinner"></span>Recomputing every fingerprint`; await DOS.sleep(500);
        const r = await DOS.api("/api/audit/verify"); b.innerHTML = `${icon("shield")}Verify the chain`;
        DOS.toast(r.intact ? `Verified: all ${r.records} records intact.` : `Broken at record ${r.broken_at_seq}.`, r.intact ? "ok" : "bad");
      };
      if (DOS.$("ev")) DOS.$("ev").onclick = async () => {
        const pack = await DOS.api("/api/governance/evidence");
        const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(pack, null, 2)], { type: "application/json" }));
        a.download = `DOS_evidence_${DOS.S.me.client.id}_${new Date().toISOString().slice(0, 10)}.json`; a.click(); DOS.toast("Evidence pack downloaded.", "ok");
      };
    },
  };

  /* ---------------------------------------------------------------- live activity */
  DOS.pages.activity = {
    title: "Live activity",
    async render(el) {
      el.innerHTML = DOS.header("Real time", "Live activity", "Everything happening in this workspace, as it happens: sign-ins, runs, decisions, rule changes, data connections, breakdowns.") +
        `<div class="split"><div class="card rise"><div class="feed" id="feed" style="max-height:none"></div></div>
          <div class="card rise" style="--i:1"><h3>What the colours mean</h3><div class="list" style="margin-top:10px">${[["ok", "Finished, approved, released"], ["warn", "Waiting for a person, risk accepted"], ["bad", "Failed, rejected, stopped"], ["agent", "Agents starting and working"], ["rules", "Rule changes (layer 2)"], ["data", "Data connections (layer 3)"], ["people", "People signing in and acting"]]
            .map(([k, t]) => `<div class="ev k-${k}"><span class="dot"></span><span>${t}</span></div>`).join("")}</div></div></div>`;
      const seen = new Set();
      const load = async () => {
        const rows = await DOS.api("/api/app/activity?limit=80"); const f = DOS.$("feed"); if (!f) return;
        const first = !seen.size;
        f.innerHTML = rows.map((e) => { const isNew = !first && !seen.has(e.id); seen.add(e.id);
          return `<div class="ev k-${esc(e.kind)} ${isNew ? "new" : ""}" ${e.run_id ? `style="cursor:pointer" data-run="${esc(e.run_id)}"` : ""}><span class="dot"></span><span>${esc(e.text)}</span><span class="small muted">${DOS.ago(e.at)}</span><span class="w">${esc(e.who || "")}${e.role ? " · " + esc(e.role) : ""}</span></div>`; }).join("") || `<p class="muted">Nothing yet.</p>`;
        DOS.qsa("[data-run]", f).forEach((d) => (d.onclick = () => DOS.go("runs/" + d.dataset.run)));
      };
      await load(); DOS.every(2500, load);
    },
  };
})();
