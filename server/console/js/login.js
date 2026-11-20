/* The sign-in screen: choose a company, choose who you are (by role), type the six-digit login code.
   No usernames, no passwords, no personal names: people are shown by role and job title only. */
"use strict";
(() => {
  const { esc, icon } = DOS;
  const L = { companies: [], company: null, people: [], person: null, demo: false };
  const LAYERS = [["L1", "The DOS app", "what each role uses"], ["L2", "Your rules", "limits and approvals, no code"],
    ["L3", "Your data", "one gate, masked, logged"], ["L4", "AI agents", "55 agents on Gemini"], ["L5", "Safety & governance", "every action checked and recorded"]];

  DOS.showLogin = async function (message) {
    DOS.$("app").innerHTML = `
    <div class="login">
      <section class="login-l">
        <div class="nodes">${Array.from({ length: 18 }, (_, i) => `<i style="left:${(i * 53) % 100}%;top:${(i * 37) % 100}%;animation-delay:${(i % 6) * .6}s;opacity:${.25 + (i % 4) * .15}"></i>`).join("")}</div>
        <div class="brandrow rise">${DOS.logo(40)}<span>digiquench</span></div>
        <div class="rise" style="--i:1"><div class="eyebrow">DOS · DigiQuench OS · built on Gemini and Google Cloud</div>
          <h1 style="margin-top:12px">The AI agent platform<br><span class="grad">that runs your operations.</span></h1></div>
        <p class="lead rise" style="--i:2">AI agents work your end-to-end processes. Your rules decide what they may do, your people approve what matters, and every action is recorded.</p>
        <div class="layers5">${LAYERS.map((l, i) => `<div class="rise" style="--i:${i + 3}"><span class="lt ${l[0]}">${l[0]}</span><b>${l[1]}</b><span class="muted">${l[2]}</span></div>`).join("")}</div>
        <p class="small muted rise" style="--i:9">Sample companies with illustrative data. © DigiQuench Technologies, Bengaluru.</p>
      </section>
      <section class="login-r">
        <div class="rise"><h2>Sign in to DOS</h2><p class="muted" style="margin:6px 0 0">Pick a company, pick your role, enter your login code. Each role sees and can do different things.</p></div>
        <div class="stepl" id="st1"><i>1</i>Company</div><div class="cogrid" id="cos">${'<div class="skel" style="height:62px"></div>'.repeat(4)}</div>
        <div class="stepl" id="st2"><i>2</i>Your role</div><div class="rolegrid" id="people"><p class="muted small">Choose a company first.</p></div>
        <div class="stepl" id="st3"><i>3</i>Login code</div>
        <form id="codeForm" class="row" autocomplete="off">
          <div class="otp" id="otp">${Array.from({ length: 6 }, (_, i) => `<input inputmode="numeric" maxlength="1" aria-label="Code digit ${i + 1}" data-i="${i}">`).join("")}</div>
          <button class="btn primary lg" id="goBtn" type="submit">${icon("arrow")}Sign in</button>
        </form>
        <div class="err" id="err">${esc(message || "")}</div>
        <p class="small muted" id="hint"></p>
      </section>
    </div>`;
    wireOtp();
    DOS.$("codeForm").onsubmit = (e) => { e.preventDefault(); submit(); };
    try { L.companies = await DOS.api("/api/auth/companies"); } catch (e) { DOS.$("err").textContent = "DOS is not reachable: " + e.message; return; }
    drawCompanies();
    const last = localStorage.getItem("dos_company");
    pickCompany(L.companies.find((c) => c.id === last) ? last : L.companies[0].id);
  };

  function drawCompanies() {
    DOS.$("cos").innerHTML = L.companies.map((c, i) => `
      <button type="button" class="cocard rise" style="--i:${i};--c:${esc(c.accent)}" data-id="${esc(c.id)}" aria-pressed="false">
        <i>${esc(DOS.initials(c.name))}</i><span><b>${esc(c.name)}</b><small>${esc(c.industry)}${c.plant ? " · live plant" : ""}</small></span></button>`).join("");
    DOS.qsa(".cocard").forEach((b) => (b.onclick = () => pickCompany(b.dataset.id)));
  }

  async function pickCompany(id) {
    L.company = id; L.person = null; localStorage.setItem("dos_company", id);
    DOS.qsa(".cocard").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.id === id)));
    DOS.$("st1").classList.add("done");
    DOS.$("people").innerHTML = '<div class="skel" style="height:80px"></div>'.repeat(3);
    const r = await DOS.api(`/api/auth/roster?client=${encodeURIComponent(id)}`);
    L.people = r.people; L.demo = r.demo;
    DOS.$("people").innerHTML = L.people.map((p, i) => `
      <button type="button" class="rolecard rise" style="--i:${i}" data-i="${i}" aria-pressed="false">
        ${p.code ? `<span class="code">${esc(p.code)}</span>` : ""}
        <span class="rn">${esc(p.role_name)}${p.layers ? " · all layers" : ""}</span><b>${esc(p.name)}</b><small>${esc(p.sees)}</small></button>`).join("");
    DOS.qsa(".rolecard").forEach((b) => (b.onclick = () => pickPerson(+b.dataset.i)));
    DOS.$("hint").innerHTML = L.demo ? "Demo workspace: each card shows its login code. Click a card to fill it in." : "Your login code was shared with you by DigiQuench.";
  }

  async function pickPerson(i) {
    L.person = L.people[i];
    DOS.qsa(".rolecard").forEach((b) => b.setAttribute("aria-pressed", String(+b.dataset.i === i)));
    DOS.$("st2").classList.add("done");
    const boxes = DOS.qsa("#otp input");
    boxes.forEach((b) => { b.value = ""; b.classList.remove("filled"); });
    if (L.person.code) {   // demo: type the code in, digit by digit
      for (let k = 0; k < 6; k++) { boxes[k].value = L.person.code[k]; boxes[k].classList.add("filled"); await DOS.sleep(55); }
      DOS.$("st3").classList.add("done"); DOS.$("goBtn").focus();
    } else boxes[0].focus();
  }

  function wireOtp() {
    const boxes = DOS.qsa("#otp input");
    boxes.forEach((b, i) => {
      b.addEventListener("input", () => { b.value = b.value.replace(/\D/g, "").slice(-1); b.classList.toggle("filled", !!b.value); if (b.value && boxes[i + 1]) boxes[i + 1].focus(); if (code().length === 6) submit(); });
      b.addEventListener("keydown", (e) => { if (e.key === "Backspace" && !b.value && boxes[i - 1]) boxes[i - 1].focus(); });
      b.addEventListener("paste", (e) => { const t = (e.clipboardData.getData("text") || "").replace(/\D/g, "").slice(0, 6); if (!t) return; e.preventDefault();
        boxes.forEach((x, k) => { x.value = t[k] || ""; x.classList.toggle("filled", !!x.value); }); if (t.length === 6) submit(); });
    });
  }
  const code = () => DOS.qsa("#otp input").map((b) => b.value).join("");

  async function submit() {
    const err = DOS.$("err"); err.textContent = "";
    if (!L.company) return (err.textContent = "Choose a company.");
    if (code().length !== 6) return (err.textContent = "Enter all six digits of your login code.");
    const btn = DOS.$("goBtn"); btn.disabled = true; btn.innerHTML = `<span class="spinner"></span>Signing in`;
    try {
      const r = await DOS.api("/api/auth/code", { method: "POST", body: { client: L.company, code: code() }, noLogout: true });
      btn.innerHTML = `${icon("check")}Welcome`; DOS.confetti(btn.getBoundingClientRect().left + 60, btn.getBoundingClientRect().top, 24);
      await DOS.sleep(350);
      await DOS.signIn(r.token);
      DOS.toast(r.user.name === r.user.role_name ? `Signed in as ${r.user.name}` : `Signed in as ${r.user.name} (${r.user.role_name})`, "ok");
    } catch (e) {
      err.textContent = e.message; btn.disabled = false; btn.innerHTML = `${icon("arrow")}Sign in`;
      const o = DOS.$("otp"); o.classList.remove("shake"); void o.offsetWidth; o.classList.add("shake");
    }
  }
})();
