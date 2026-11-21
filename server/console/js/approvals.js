/* Approvals: everything an agent may not do alone, with the evidence, decided by a person.
   The server re-checks the decision against today's rules, the designated approver and the four-eyes rule. */
"use strict";
(() => {
  const { esc, icon } = DOS;

  DOS.pages.approvals = {
    title: "Approvals",
    async render(el) {
      const canDecide = DOS.can("approval.decide");
      el.innerHTML = DOS.header("Layer 5 · people decide what matters", "Approvals",
        canDecide ? "Agents stopped and are waiting for you. Each card shows what the agent wants to do, the details, and the company rule that sent it here. Approve and the agent finishes the job; reject and it stops."
          : "Read-only for your role. Approvers and the Business Owner decide these.",
        `<div class="seg" id="af"><button data-v="pending" class="on">Waiting</button><button data-v="approved">Approved</button><button data-v="rejected">Rejected</button></div>`) + `<div id="aps">${DOS.skeleton(3)}</div>`;
      let status = "pending";
      DOS.qsa("#af button").forEach((b) => (b.onclick = () => { status = b.dataset.v; DOS.qsa("#af button").forEach((x) => x.classList.toggle("on", x === b)); load(); }));
      async function load() {
        const rows = await DOS.api(`/api/approvals?status=${status}`);
        const box = DOS.$("aps"); if (!box) return;
        if (!rows.length) { box.innerHTML = DOS.empty("check", status === "pending" ? "Nothing is waiting" : "Nothing here yet", status === "pending" ? "Agents finished everything within the company's rules. New items appear here within seconds." : ""); return; }
        box.innerHTML = `<div class="grid g2">${rows.map((a, i) => card(a, i, canDecide && status === "pending")).join("")}</div>`;
        DOS.qsa("[data-ok],[data-no]", box).forEach((b) => (b.onclick = () => decide(b.dataset.ok || b.dataset.no, !!b.dataset.ok)));
        DOS.qsa("[data-run]", box).forEach((b) => (b.onclick = () => DOS.go("runs/" + b.dataset.run)));
      }
      async function decide(id, approved) {
        const note = DOS.qs(`#note-${CSS.escape(id)}`)?.value || "";
        const c = DOS.$("apc-" + id);
        try {
          await DOS.api(`/api/approvals/${encodeURIComponent(id)}/decision`, { method: "POST", body: { approved, note } });
          c.classList.add("gone"); if (approved) { const r = c.getBoundingClientRect(); DOS.confetti(r.left + 80, r.top + 30, 20); }
          DOS.toast(approved ? "Approved. The agent is finishing the job." : "Rejected. Nothing was done.", approved ? "ok" : "");
          setTimeout(load, 380); DOS.refreshMe();
        } catch (e) { DOS.toast(e.message, "bad"); }
      }
      await load();
      DOS.every(5000, () => status === "pending" && load());
    },
  };

  function card(a, i, canDecide) {
    const named = (a.designated || []).map((u) => u.title || u.name).join(", ");
    return `<div class="apcard rise" style="--i:${i}" id="apc-${esc(a.id)}">
      <div class="row"><span class="ico" style="--ic:var(--accent)">${icon("clock")}</span><div class="grow"><b style="font-size:15px">${esc(a.agent_name)} wants to ${esc(DOS.title(a.tool).toLowerCase())}</b>
        <div class="small muted">${DOS.ago(a.created_at)} · asked by ${esc(a.requested_by)}</div></div>${DOS.status(a.status)}</div>
      <div class="args">${Object.entries(a.args || {}).slice(0, 8).map(([k, v]) => `<div><span>${esc(DOS.title(k))}</span><b>${esc(DOS.argText(v))}</b></div>`).join("")}</div>
      <div class="small" style="color:var(--text2)">${icon("shield")} <b>Why a person decides:</b> ${esc(a.why || "Company rule")}</div>
      ${named ? `<div class="small muted">Only ${esc(named)} may decide this action for this company.</div>` : ""}
      ${a.decided_by ? `<div class="small muted">Decided by ${esc(a.decided_by)} ${DOS.ago(a.decided_at)}${a.note ? ": " + esc(a.note) : ""}</div>` : ""}
      ${canDecide ? `<input class="in" id="note-${esc(a.id)}" placeholder="Note for the audit trail (optional)"><div class="row"><button class="btn good" data-ok="${esc(a.id)}">${icon("check")}Approve</button>
        <button class="btn bad" data-no="${esc(a.id)}">${icon("x")}Reject</button><button class="btn ghost sm right" data-run="${esc(a.run_id)}">See the run</button></div>`
        : `<div class="row"><button class="btn ghost sm" data-run="${esc(a.run_id)}">See the run</button></div>`}</div>`;
  }
})();
