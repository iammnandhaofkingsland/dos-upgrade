/* Work orders: the technician's jobs. Acknowledge, start, and close with the confirmed cause.
   The confirmed cause is written back to the repair history, so the next diagnosis learns from this repair. */
"use strict";
(() => {
  const { esc, icon, num } = DOS;
  const FLOW = ["assigned", "acknowledged", "in_progress", "resolved"];
  const NEXT = { assigned: ["ack", "Acknowledge", "check"], acknowledged: ["start", "Start repair", "wrench"], in_progress: ["resolve", "Close the job", "flag"] };

  DOS.pages.workorders = {
    title: "Work orders",
    async render(el) {
      const tech = DOS.role() === "technician";
      el.innerHTML = DOS.header("Manufacturing · repairs", tech ? "My work orders" : "Work orders",
        tech ? "DOS assigned these to you based on skill, shift and who is free. Acknowledge quickly: if nobody acknowledges in time, DOS escalates." : "Every repair DOS dispatched, with who has it and how far it has got.") + `<div id="wo">${DOS.skeleton(3)}</div>`;
      const causes = await DOS.api("/api/plant/causes");
      const canAct = DOS.can("workorder.update");
      async function load() {
        const rows = await DOS.api(`/api/workorders${tech ? "?mine=true" : ""}`);
        const box = DOS.$("wo"); if (!box) return;
        const sig = JSON.stringify(rows.map((w) => [w.id, w.status])); if (box.dataset.sig === sig) return; box.dataset.sig = sig;
        if (!rows.length) { box.innerHTML = DOS.empty("wrench", "No work orders", tech ? "When a machine breaks down, DOS dispatches the job to the right technician here within seconds." : "Simulate a fault on the plant floor to see one."); return; }
        box.innerHTML = `<div class="grid g2">${rows.map((w, i) => card(w, i, canAct)).join("")}</div>`;
        DOS.qsa("[data-act]", box).forEach((b) => (b.onclick = () => act(b.dataset.id, b.dataset.act)));
      }
      async function act(id, action) {
        if (action !== "resolve") {
          try { await DOS.api(`/api/workorders/${encodeURIComponent(id)}/${action}`, { method: "POST", body: { notes: "" } }); DOS.toast(action === "ack" ? "Acknowledged. The plant head can see you are on it." : "Repair started. The clock is running.", "ok"); DOS.$("wo").dataset.sig = ""; load(); }
          catch (e) { DOS.toast(e.message, "bad"); }
          return;
        }
        DOS.modal(`<h3>Close the job</h3><p class="muted">Confirm what you actually found. DOS adds it to the repair history so future diagnoses improve.</p>
          <label class="f" style="margin-top:12px">Confirmed cause<select class="in" id="wc">${causes.map((c) => `<option value="${esc(c.key)}">${esc(c.label)}</option>`).join("")}</select></label>
          <label class="f" style="margin-top:10px">Minutes the repair took<input class="in" id="wm" type="number" min="1" value="45"></label>
          <label class="f" style="margin-top:10px">What you did<textarea class="in" id="wn" rows="3" placeholder="e.g. replaced front bearing pair, set preload, test run OK"></textarea></label>
          <div class="acts"><button class="btn" data-close>Cancel</button><button class="btn good" id="wGo">${icon("check")}Close the job</button></div>`, (sc, close) => {
          DOS.qs("#wGo", sc).onclick = async () => {
            try { await DOS.api(`/api/workorders/${encodeURIComponent(id)}/resolve`, { method: "POST", body: { confirmed_cause: DOS.qs("#wc", sc).value, minutes: +DOS.qs("#wm", sc).value || 1, notes: DOS.qs("#wn", sc).value } });
              close(); DOS.confetti(innerWidth / 2, innerHeight / 3, 50); DOS.toast("Job closed. The machine is back and the repair history has learned from it.", "ok"); DOS.$("wo").dataset.sig = ""; load(); }
            catch (e) { DOS.toast(e.message, "bad"); }
          };
        });
      }
      await load();
      DOS.every(3000, load);
    },
  };

  function card(w, i, canAct) {
    const at = FLOW.indexOf(w.status), nx = NEXT[w.status];
    return `<div class="card rise" style="--i:${i};${w.escalated ? "border-color:rgba(248,113,113,.5)" : ""}">
      <div class="row"><span class="ico" style="--ic:${w.priority === "high" ? "var(--bad)" : "var(--accent)"}">${icon("wrench")}</span><div class="grow"><b style="font-size:15px">${esc(w.machine_name)}</b><div class="small muted">${esc(w.id)} · ${esc(w.priority)} priority · ${DOS.ago(w.assigned_at)}</div></div>${DOS.status(w.status)}</div>
      <p style="margin:10px 0 6px"><b>${esc(w.title)}</b></p><p class="small" style="color:var(--text2);margin:0 0 10px;white-space:pre-wrap">${esc((w.diagnosis || "").slice(0, 420))}</p>
      <div class="args" style="margin-bottom:12px"><div><span>Technician</span><b>${esc(w.technician_name || "Not assigned")}</b></div><div><span>Spare part</span><b>${esc(w.part || "None needed")}</b></div>
        ${w.resolution ? `<div><span>Confirmed cause</span><b>${esc(DOS.title(w.resolution.confirmed_cause || ""))}</b></div><div><span>Repair time</span><b>${num(w.resolution.minutes)} min</b></div>` : ""}</div>
      <div class="stepper">${FLOW.map((s, k) => `${k ? `<i class="${k <= at ? "on" : ""}"></i>` : ""}<b class="${k <= at ? "on" : ""}" title="${DOS.title(s)}">${k < at || s === "resolved" && at === 3 ? "✓" : k + 1}</b>`).join("")}</div>
      <div class="row small muted" style="justify-content:space-between;margin-top:4px">${FLOW.map((s) => `<span>${DOS.title(s)}</span>`).join("")}</div>
      ${w.escalated ? `<p class="small" style="color:#fca5a5;margin:10px 0 0">${icon("alert")} Escalated: not acknowledged in time.</p>` : ""}
      ${canAct && nx ? `<div class="row" style="margin-top:12px"><button class="btn ${nx[0] === "resolve" ? "good" : "primary"}" data-id="${esc(w.id)}" data-act="${nx[0]}">${icon(nx[2])}${nx[1]}</button></div>` : ""}</div>`;
  }
})();
