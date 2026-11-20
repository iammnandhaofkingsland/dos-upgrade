/* Ask DOS: plain-English questions about this company's own operations. It reads and explains; it never acts. */
"use strict";
(() => {
  const { esc, icon } = DOS;
  const SUGG = {
    owner: ["What is waiting for approval?", "Explain the last run", "Did anything fail today?", "How much have we spent on Gemini today?", "Approve everything for me"],
    operator: ["Explain the last run", "Which agents failed today?", "What is waiting for approval?", "Is the emergency stop clear?"],
    approver: ["What is waiting for approval?", "Why does the latest item need a person?", "Is any machine down?"],
    technician: ["Is any machine down?", "What is the likely cause on the open breakdown?"],
    auditor: ["Did anything fail today?", "Explain the last run", "Is the emergency stop clear?"],
  };

  DOS.openAsk = function () {
    const dr = DOS.$("drawer");
    dr.className = "drawer open";
    dr.innerHTML = `<div class="dhead"><span class="ico" style="--ic:var(--accent)">${icon("chat")}</span><div class="grow"><b>Ask DOS</b><div class="small muted">Answers from your own records. It can explain, never act.</div></div><button class="btn sm ghost" id="aClose">${icon("x")}</button></div>
      <div class="dbody chat" id="chat"><div class="small muted">Ask in plain English. Every answer lists what DOS looked at. Questions that try to give orders are refused and recorded.</div>
        <div class="sugg">${(SUGG[DOS.role()] || SUGG.owner).map((s) => `<button type="button">${esc(s)}</button>`).join("")}</div></div>
      <form class="dform" id="aForm"><input class="in" id="aIn" placeholder="e.g. What is waiting for approval?" autocomplete="off"><button class="btn primary">${icon("arrow")}</button></form>`;
    DOS.$("aClose").onclick = () => dr.classList.remove("open");
    DOS.qsa(".sugg button", dr).forEach((b) => (b.onclick = () => ask(b.textContent)));
    DOS.$("aForm").onsubmit = (e) => { e.preventDefault(); ask(DOS.$("aIn").value); };
    setTimeout(() => DOS.$("aIn").focus(), 300);
  };

  async function ask(q) {
    q = (q || "").trim(); if (q.length < 2) return;
    DOS.$("aIn").value = "";
    const chat = DOS.$("chat");
    chat.insertAdjacentHTML("beforeend", `<div class="q">${esc(q)}</div><div class="a"><span class="spinner"></span> Looking at your records…</div>`);
    const box = chat.lastElementChild; chat.scrollTop = 1e9;
    try {
      const r = await DOS.api("/api/app/ask", { method: "POST", body: { question: q } });
      box.innerHTML = r.blocked ? `<span class="chip bad">Refused by the safety screen</span><br>` : "";
      const t = document.createElement("span"); box.appendChild(t);
      await DOS.typewrite(t, r.answer, 7);
      box.insertAdjacentHTML("beforeend", `<div class="tools">${r.engine === "gemini" ? "Answered by Gemini" : r.engine === "rules" ? "Answered from records (simulation)" : "Safety screen"}${r.looked_up.length ? " · looked at " + r.looked_up.join(", ") : ""}</div>`);
    } catch (e) { box.textContent = e.message; }
    chat.scrollTop = 1e9;
  }
})();
