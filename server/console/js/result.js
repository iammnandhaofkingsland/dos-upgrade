/* Outcome card: turns an agent's answer into a designed, animated result.
   DOS.result(run, {agent})  -> HTML for a finished run (done / waiting for a person / failed / stopped)
   DOS.rich(text)            -> safe, formatted HTML for any model text (Ask DOS, traces)
   DOS.animateResult(el)     -> plays the entrance: icon draws, metrics count up, findings appear one by one
   The text is parsed, never trusted as HTML: lists, "Label: value" lines, **bold**, `code`, IDs, amounts and
   percentages are recognised and styled. Works the same for Gemini answers and simulated answers. */
"use strict";
(() => {
  const { esc, icon, num } = DOS;

  const ID = /\b([A-Z]{2,5}(?:-[A-Z]{1,3})?-\d{2,6}[A-Z]?)\b/g;
  const MONEY = /((?:Rs\.?|INR|₹)\s?[\d,]+(?:\.\d+)?(?:\s?(?:lakh|crore|k))?)/gi;
  const PCT = /(\b\d+(?:\.\d+)?\s?%)/g;
  const BIG = /(\b\d{1,3}(?:,\d{2,3})+(?:\.\d+)?\b)/g;

  // inline formatting on already-escaped text
  function inline(s) {
    return s
      .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(MONEY, '<span class="rv money">$1</span>')
      .replace(PCT, '<span class="rv pct">$1</span>')
      .replace(ID, '<span class="rv id">$1</span>')
      .replace(BIG, (m, a, off, all) => (/class="rv[^>]*>[^<]*$/.test(all.slice(0, off)) ? m : `<span class="rv n">${a}</span>`));
  }

  const yesNo = (t) => String(t).replace(/\bTrue\b/g, "yes").replace(/\bFalse\b/g, "no").replace(/\bNone\b/g, "none");
  // text -> blocks: {lead}, {p}, {h}, {li, label, facts}, {kv:[k,v]}
  function parse(text) {
    const lines = String(text || "").replace(/\r/g, "").split("\n");
    const blocks = [];
    let sim = false;
    for (let raw of lines) {
      let l = raw.trim();
      if (!l) continue;
      if (/^\[simulation\]/i.test(l)) { sim = true; l = l.replace(/^\[simulation\]\s*/i, ""); if (!l) continue; }
      let m;
      if ((m = l.match(/^#{1,4}\s+(.+)/))) { blocks.push({ h: m[1] }); continue; }
      if ((m = l.match(/^(?:[-*•]|\d+[.)])\s+(.+)/))) {
        const item = m[1];
        const lm = item.match(/^\**([A-Za-z][A-Za-z0-9 _/&()-]{1,40}?)\**\s*:\s+(.+)$/);
        if (lm) blocks.push({ li: true, label: lm[1], facts: lm[2].split(/;\s+/) });
        else blocks.push({ li: true, label: "", facts: [item] });
        continue;
      }
      if ((m = l.match(/^\**([A-Z][A-Za-z0-9 _/&()-]{1,28})\**\s*:\s+(.{1,160})$/)) && !/[.!?]\s/.test(m[2])) { blocks.push({ kv: [m[1], m[2]] }); continue; }
      blocks.push({ p: l });
    }
    const first = blocks.findIndex((b) => b.p);
    if (first > -1) { blocks[first].lead = true; }
    return { blocks, sim };
  }

  const TOOL_IC = (label) => {
    const s = label.toLowerCase();
    if (/hold|block|stop|refus/.test(s)) return "shield";
    if (/send|message|email|notify|whatsapp/.test(s)) return "chat";
    if (/order|purchase|reorder|price/.test(s)) return "cart";
    if (/draft|save|report|note|listing/.test(s)) return "doc";
    if (/task|work order|dispatch|assign/.test(s)) return "check";
    if (/sql|table|profile|dataset|catalog|query/.test(s)) return "db";
    if (/verify|check|risk|score|match/.test(s)) return "eye";
    return "bolt";
  };

  DOS.rich = (text) => {
    const { blocks } = parse(text);
    let html = "", list = [];
    const flush = () => { if (list.length) { html += `<ul class="rlist">${list.join("")}</ul>`; list = []; } };
    blocks.forEach((b) => {
      if (b.li) { list.push(`<li>${b.label ? `<b>${esc(DOS.title(b.label))}</b> ` : ""}${b.facts.map((f) => inline(esc(f))).join("; ")}</li>`); return; }
      flush();
      if (b.h) html += `<h5 class="rh">${inline(esc(b.h))}</h5>`;
      else if (b.kv) html += `<div class="rkv"><span>${esc(b.kv[0])}</span><b>${inline(esc(b.kv[1]))}</b></div>`;
      else html += `<p class="${b.lead ? "rlead" : ""}">${inline(esc(b.p))}</p>`;
    });
    flush();
    return html;
  };

  const STATE = {
    completed: ["ok", "Done", "Task completed end to end", "check"],
    waiting_approval: ["wait", "Waiting for a person", "The agent prepared the action. It runs only after approval.", "clock"],
    failed: ["bad", "Run failed", "Nothing was changed. The reason and the fix are below.", "x"],
    stopped: ["bad", "Stopped", "The emergency stop halted this run.", "x"],
    running: ["run", "Still working", "The agent is still running. Open the trace to follow it.", "pulse"],
  };

  const glyph = (k) => k === "ok"
    ? `<svg viewBox="0 0 52 52"><circle class="rc" cx="26" cy="26" r="23"/><path class="rp" d="M15 27.5l7.2 7.2L37.5 19"/></svg>`
    : k === "wait"
      ? `<svg viewBox="0 0 52 52"><circle class="rc" cx="26" cy="26" r="23"/><path class="rp" d="M26 14v13l8 5"/></svg>`
      : k === "run"
        ? `<svg viewBox="0 0 52 52"><circle class="rc spin" cx="26" cy="26" r="23"/><path class="rp" d="M17 26h18"/></svg>`
        : `<svg viewBox="0 0 52 52"><circle class="rc" cx="26" cy="26" r="23"/><path class="rp" d="M18 18l16 16M34 18L18 34"/></svg>`;

  DOS.result = (run, opts = {}) => {
    const [k, title, sub, ic] = STATE[run.status] || ["ok", DOS.title(run.status), "", "check"];
    const text = run.output || (run.status === "failed" ? "" : run.status === "waiting_approval" ? "The agent has prepared the action and is waiting for a person to approve it." : "");
    const { blocks, sim } = parse(text);
    const findings = blocks.filter((b) => b.li);
    const kvs = blocks.filter((b) => b.kv);
    const paras = blocks.filter((b) => b.p || b.h);
    const simulated = run.simulated || sim;
    const secs = (run.latency_ms || 0) / 1000;
    const metrics = [
      ["clock", secs >= 1 ? secs.toFixed(1) : (run.latency_ms || 0), secs >= 1 ? "seconds" : "ms", "Time"],
      ["model", run.model_calls || 0, simulated ? "simulated calls" : "Gemini calls", "Model"],
      ["bolt", run.tool_calls || 0, "tool calls", "Tools"],
      ["coin", run.cost_inr || 0, "rupees", "Cost"],
    ];
    const agent = opts.agent || run.agent_name || DOS.title(run.agent_id || "");
    const when = run.ended_at || run.created_at;
    return `<div class="res res-${k}">
      <div class="res-head">
        <div class="res-ico">${glyph(k)}</div>
        <div class="grow"><div class="res-k">Outcome</div><h4>${esc(title)}</h4><div class="res-sub">${esc(sub)}</div></div>
        <div class="res-tags">${DOS.simChip(simulated)}${agent ? `<span class="chip">${esc(agent)}</span>` : ""}${when ? `<span class="small muted">${DOS.ago(when)}</span>` : ""}</div>
      </div>
      ${opts.metrics === false ? "" : `<div class="res-metrics">${metrics.map(([i, v, u, l], n) => `<div class="rm" style="--d:${n}"><span class="ic-s">${icon(i)}</span><div><b data-to="${Number(v) || 0}" data-dec="${String(v).includes(".") ? 1 : l === "Cost" ? 2 : 0}">0</b><small>${esc(u)}</small></div></div>`).join("")}</div>`}
      ${run.status === "failed" || run.status === "stopped" ? `<div class="res-fix">${icon("alert")}<div><b>${esc(run.error_hint || "The run stopped before finishing.")}</b>${run.error ? `<details><summary>Technical detail</summary><code>${esc(run.error)}</code></details>` : ""}</div></div>` : ""}
      ${paras.length ? `<div class="res-body">${paras.map((b, n) => b.h ? `<h5 class="rh">${inline(esc(b.h))}</h5>` : `<p class="${b.lead ? "rlead" : ""} rin" style="--d:${n}">${inline(esc(b.p))}</p>`).join("")}</div>` : ""}
      ${kvs.length ? `<div class="res-kv">${kvs.map((b, n) => `<div class="rin" style="--d:${n}"><span>${esc(b.kv[0])}</span><b>${inline(esc(b.kv[1]))}</b></div>`).join("")}</div>` : ""}
      ${findings.length ? `<div class="res-steps"><div class="res-k">What the agent did</div>${findings.map((f, n) => `<div class="rstep rin" style="--d:${Math.min(n, 10)}">
          <span class="rdot">${icon(TOOL_IC(f.label || f.facts[0]))}</span>
          <div class="grow">${f.label ? `<b>${esc(DOS.title(f.label))}</b>` : ""}<div class="rfacts">${f.facts.map((x) => `<span>${inline(esc(yesNo(x)))}</span>`).join("")}</div></div></div>`).join("")}</div>` : ""}
    </div>`;
  };

  DOS.animateResult = (root) => {
    if (!root) return;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    root.querySelectorAll(".res-metrics b[data-to]").forEach((b) => {
      const to = +b.dataset.to, dec = +b.dataset.dec;
      const fmt = (v) => (dec ? v.toFixed(dec) : Math.round(v).toLocaleString("en-IN"));
      if (reduce || !to) { b.textContent = fmt(to); return; }
      const t0 = performance.now(), dur = 700;
      const step = (t) => { const k = Math.min(1, (t - t0) / dur); b.textContent = fmt(to * (1 - Math.pow(1 - k, 3))); if (k < 1) requestAnimationFrame(step); };
      requestAnimationFrame(step);
    });
  };
})();
