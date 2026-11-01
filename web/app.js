/* Counted website behaviour. No framework; every feature degrades to readable static content. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const API = location.protocol.startsWith("http") ? "" : "http://localhost:8080";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const LABEL = { direct: "Direct", indirect: "Indirect", not_related: "Not related", possible: "Can’t commit" };
  const pretty = (s) => String(s || "").replaceAll("_", " ");

  /* ------------------------------------------------------------ info tooltips */
  const tip = document.createElement("div");
  tip.className = "tip"; tip.id = "tip"; tip.setAttribute("role", "tooltip");
  document.body.appendChild(tip);
  let owner = null, openTimer = null, closeTimer = null, warm = false, warmTimer = null;

  function place(btn) {
    const r = btn.getBoundingClientRect(), t = tip.getBoundingClientRect();
    let x = r.left, y = r.bottom + 10, ox = "left", oy = "top";
    if (x + t.width > innerWidth - 16) { x = Math.max(16, r.right - t.width); ox = "right"; }
    if (y + t.height > innerHeight - 16) { y = r.top - t.height - 10; oy = "bottom"; }
    tip.style.left = `${x}px`; tip.style.top = `${y}px`; tip.style.setProperty("--origin", `${oy} ${ox}`);
  }
  function show(btn) {
    clearTimeout(closeTimer);
    if (owner && owner !== btn) owner.setAttribute("aria-expanded", "false");
    owner = btn;
    tip.innerHTML = btn.dataset.tip;
    btn.setAttribute("aria-expanded", "true");
    btn.setAttribute("aria-describedby", "tip");
    tip.classList.toggle("instant", warm);   // once one is open, the next opens without delay or motion
    place(btn);
    requestAnimationFrame(() => tip.classList.add("on"));
    warm = true; clearTimeout(warmTimer);
  }
  function hide() {
    if (!owner) return;
    owner.setAttribute("aria-expanded", "false"); owner.removeAttribute("aria-describedby");
    tip.classList.remove("on"); owner = null;
    warmTimer = setTimeout(() => (warm = false), 400);
  }
  $$(".i").forEach((btn) => {
    btn.setAttribute("aria-expanded", "false");
    const text = btn.dataset.tip.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    btn.setAttribute("aria-label", "More about this: " + text.slice(0, 60));
    const fine = matchMedia("(hover: hover) and (pointer: fine)").matches;
    if (fine) {
      btn.addEventListener("mouseenter", () => { clearTimeout(openTimer); openTimer = setTimeout(() => show(btn), warm ? 0 : 220); });
      btn.addEventListener("mouseleave", () => { clearTimeout(openTimer); closeTimer = setTimeout(hide, 160); });
    }
    btn.addEventListener("focus", () => show(btn));
    btn.addEventListener("blur", () => { closeTimer = setTimeout(hide, 120); });
    btn.addEventListener("click", (e) => { e.stopPropagation(); owner === btn && tip.classList.contains("on") ? hide() : show(btn); });
  });
  tip.addEventListener("mouseenter", () => clearTimeout(closeTimer));
  tip.addEventListener("mouseleave", () => (closeTimer = setTimeout(hide, 160)));
  document.addEventListener("click", (e) => { if (!tip.contains(e.target)) hide(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });
  addEventListener("scroll", () => owner && place(owner), { passive: true });

  /* ------------------------------------------------------------ entrances */
  const io = new IntersectionObserver((entries) => {
    entries.forEach((en) => { if (en.isIntersecting) { en.target.classList.add("seen"); io.unobserve(en.target); } });
  }, { rootMargin: "0px 0px -12% 0px" });
  $$(".in, .stairs").forEach((el) => io.observe(el));

  /* ------------------------------------------------------------ before / after */
  const cmp = $(".compare");
  if (cmp) {
    const range = $("input", cmp);
    const set = (v) => cmp.style.setProperty("--split", `${v}%`);
    range.addEventListener("input", () => set(range.value));
    cmp.addEventListener("pointermove", (e) => {
      if (e.pointerType !== "mouse") return;
      const r = cmp.getBoundingClientRect();
      const v = Math.min(100, Math.max(0, ((e.clientX - r.left) / r.width) * 100));
      range.value = v; set(v);
    });
  }

  /* ------------------------------------------------------------ markdown (documents are ours, but escape anyway) */
  function md(src) {
    const lines = esc(src).split("\n"); let html = "", inTable = false, inList = false;
    const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/_(.+?)_/g, "<em>$1</em>")
      .replace(/&lt;sub&gt;(.+?)&lt;\/sub&gt;/g, "<small>$1</small>");
    for (const raw of lines) {
      const l = raw.trimEnd();
      if (/^\|/.test(l)) {
        if (/^\|[\s|-]+\|$/.test(l)) continue;
        if (!inTable) { html += "<table>"; inTable = true; }
        html += "<tr>" + l.slice(1, -1).split("|").map((c) => `<td>${inline(c.trim())}</td>`).join("") + "</tr>"; continue;
      } else if (inTable) { html += "</table>"; inTable = false; }
      if (/^- /.test(l)) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${inline(l.slice(2))}</li>`; continue; }
      else if (inList) { html += "</ul>"; inList = false; }
      if (/^# /.test(l)) html += `<h1>${inline(l.slice(2))}</h1>`;
      else if (/^## /.test(l)) html += `<h2>${inline(l.slice(3))}</h2>`;
      else if (/^&gt; /.test(l)) html += `<blockquote>${inline(l.slice(5))}</blockquote>`;
      else if (l) html += `<p>${inline(l)}</p>`;
    }
    return html + (inTable ? "</table>" : "") + (inList ? "</ul>" : "");
  }

  /* ------------------------------------------------------------ case file rendering */
  let current = null, docKey = "certifier_statement";

  function renderFacts(facts) {
    const ev = facts?.evidence || [];
    $("#facts").innerHTML = ev.length
      ? ev.map((e) => `<div class="quote"><q>${esc(e.quote || e.detail)}</q><span>${esc(pretty(e.mechanism))} · ${esc(e.detail)}</span></div>`).join("")
      : `<p class="status">${facts?.unrelated_explanation ? esc(facts.unrelated_explanation) : "No disaster-related circumstance recorded yet."}</p>`;
    $("#s-facts").classList.toggle("done", ev.length > 0 || !!facts?.unrelated_explanation);
  }
  function renderRecords(ctx, facts) {
    if (!ctx) return;
    const rows = [
      ["Place", [facts?.county && `${facts.county} County`, facts?.state].filter(Boolean).join(", ") || "not checked"],
      ["Declaration", ctx.declared ? `${ctx.declaration} · ${ctx.declaration_title || ctx.incident_type || ""}` : "none found for this place and date"],
      ["Incident period", ctx.incident_begin ? `${ctx.incident_begin} to ${ctx.incident_end || "ongoing"}` : "n/a"],
      ["Death in window", ctx.within_incident_window == null ? "n/a" : ctx.within_incident_window ? (ctx.days_after_incident_end ? `yes, ${ctx.days_after_incident_end} days after` : "yes") : "no"],
      ["Funeral aid program", ctx.individual_assistance ? "Individual Assistance approved" : "not confirmed"],
      ["NWS warnings", (ctx.nws_warnings || []).slice(0, 4).join("; ") || "none found"],
    ];
    $("#records").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("");
    $("#s-records").classList.add("done");
  }
  function renderPanel(p) {
    const seats = [["CDC decision tree", p.rules], ["Claude examiner", p.examiner], ["Amazon Nova examiner", p.second_examiner], ["Adjudicator", p.adjudicator]];
    $("#seats").innerHTML = seats.map(([who, v], i) => v
      ? `<div class="seat"><span class="who">${who}</span><span class="lab">${LABEL[v.label] || v.label}</span><span class="conf">${v.mechanism ? esc(pretty(v.mechanism)) + " · " : ""}${Math.round((v.confidence || 0) * 100)}%</span></div>`
      : `<div class="seat skip"><span class="who">${who}</span><span class="lab">${i === 3 ? (p.unanimous ? "Not needed: the panel agreed" : "Unavailable") : "Unavailable"}</span></div>`).join("");
    $("#s-panel").classList.add("done");
    const f = p.final;
    const v = $("#verdict");
    v.className = `verdict ${f.label}`;
    v.innerHTML = `<div class="big">${LABEL[f.label] || f.label}</div><p class="chain">${esc(f.causal_chain)}</p>` +
      (f.how_injury_occurred ? `<div class="item43"><strong>How injury occurred (Item 43, draft):</strong> ${esc(f.how_injury_occurred)}</div>` : "") +
      (f.missing?.length ? `<div class="item43"><strong>Open questions:</strong> ${esc(f.missing.join("; "))}</div>` : "");
    $("#s-verdict").classList.add("done");
  }
  function renderDocs(docs) {
    current = docs;
    $("#dl").disabled = !docs;
    if (!docs) return;
    const d = docs[docKey];
    $("#doc").innerHTML = typeof d === "string" ? md(d) : `<pre>${esc(JSON.stringify(d, null, 2))}</pre>`;
    $("#s-docs").classList.add("done");
  }
  function renderAll(r) {
    const steps = [() => renderFacts(r.facts), () => renderRecords(r.context, r.facts), () => renderPanel(r.panel), () => renderDocs(r.documents)];
    const ids = ["#s-facts", "#s-records", "#s-panel", "#s-verdict"];
    steps.forEach((fn, i) => setTimeout(() => { fn(); const el = $(ids[i]); el.classList.remove("reveal"); void el.offsetWidth; el.classList.add("reveal"); }, i * 220));
    setTimeout(() => $("#s-docs").classList.add("done"), 900);
  }
  function resetCase() {
    $$(".casefile .step").forEach((s) => s.classList.remove("done", "reveal"));
    $("#recorded").hidden = true;
    $("#facts").innerHTML = '<p class="status">Listening…</p>';
    $("#records").innerHTML = "<dt>Status</dt><dd>Checking FEMA and the Weather Service…</dd>";
    $$("#seats .seat").forEach((s) => { s.className = "seat"; $(".lab", s).textContent = "·"; $(".conf", s)?.remove(); });
    $("#verdict").className = "verdict possible";
    $("#verdict").innerHTML = '<div class="big">Working</div><p class="chain">The panel decides once the facts and records are in.</p>';
    current = null; $("#doc").innerHTML = "<p>Documents appear after a determination.</p>"; $("#dl").disabled = true;
  }
  $$("#doc-tabs button").forEach((b) => b.addEventListener("click", () => {
    $$("#doc-tabs button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    docKey = b.dataset.doc; renderDocs(current);
  }));
  $("#dl").addEventListener("click", () => {
    if (!current) return;
    const d = current[docKey], json = typeof d !== "string";
    const blob = new Blob([json ? JSON.stringify(d, null, 2) : d], { type: json ? "application/json" : "text/markdown" });
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `counted-${docKey}.${json ? "json" : "md"}` });
    a.click(); URL.revokeObjectURL(a.href);
  });

  /* ------------------------------------------------------------ read mode */
  let samples = [], chosen = null;
  async function loadSamples() {
    try { samples = await (await fetch("samples.json")).json(); } catch { samples = []; }
    $("#chips").innerHTML = samples.map((s) => `<button class="chip" type="button" aria-pressed="false" data-id="${s.id}">${esc(s.title)}<small>${esc(s.disaster)}</small></button>`).join("");
    $$("#chips .chip").forEach((c) => c.addEventListener("click", () => pick(c.dataset.id)));
    pick("oxygen", false);
    // Show a finished case on arrival so the product is visible before anyone clicks.
    const rec = await fetch("recorded/oxygen.json").then((x) => x.json()).catch(() => null);
    if (rec && !current) {
      renderAll(rec);
      status(`Showing a recorded run from ${rec.recorded_at?.slice(0, 10)}. Press “Find the disaster” to run it live.`);
    }
  }
  function pick(id, focus = true) {
    chosen = samples.find((s) => s.id === id);
    $$("#chips .chip").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.id === id)));
    if (chosen) $("#account").value = chosen.account;
    if (focus && mode === "talk" && chosen) startInterview(chosen.language);
  }
  $("#account").addEventListener("input", () => {
    if (chosen && $("#account").value !== chosen.account) { chosen = null; $$("#chips .chip").forEach((c) => c.setAttribute("aria-pressed", "false")); }
  });

  let ticking = null;
  $("#run").addEventListener("click", async () => {
    const account = $("#account").value.trim();
    if (account.length < 40) { status("Tell Counted a little more: age, place, date of death and what happened.", true); return; }
    resetCase(); $("#run").disabled = true;
    const t0 = performance.now();
    const say = ["Reading the account", "Checking FEMA and the Weather Service", "The panel is deciding", "Drafting the documents"];
    ticking = setInterval(() => {
      const s = (performance.now() - t0) / 1000;
      status(`<span class="spin" aria-hidden="true"></span> ${say[Math.min(3, Math.floor(s / 4))]}… ${s.toFixed(0)}s`);
    }, 250);
    try {
      const r = await fetch(`${API}/v1/demo/assess`, { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ account, language: chosen?.language || (/[ñáéíóú]|\b(murió|huracán|luz)\b/i.test(account) ? "es" : "en") }) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
      const data = await r.json();
      status(`Done in ${data.elapsed_seconds}s. Every step below ran live.`);
      renderAll(data);
    } catch (err) {
      if (chosen) {
        const rec = await fetch(`recorded/${chosen.id}.json`).then((x) => x.json()).catch(() => null);
        if (rec) {
          $("#recorded").hidden = false;
          $("#recorded").textContent = `The live service didn’t answer (${err.message}), so this is a real run of the same case recorded on ${rec.recorded_at?.slice(0, 10)}.`;
          status("Showing a recorded run."); renderAll(rec);
        } else status(`Counted couldn’t be reached: ${err.message}. Try again in a moment.`, true);
      } else status(`Counted couldn’t be reached: ${err.message}. Pick a sample case to see a recorded run.`, true);
    } finally { clearInterval(ticking); $("#run").disabled = false; }
  });
  function status(html, err = false) { const s = $("#status"); s.innerHTML = html; s.classList.toggle("err", err); }

  /* ------------------------------------------------------------ talk mode */
  let mode = "read", sid = null, busy = false;
  $$(".modes button").forEach((b) => b.addEventListener("click", () => {
    mode = b.dataset.mode;
    $$(".modes button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    $("#read-pane").hidden = mode !== "read"; $("#read-pane").style.display = mode === "read" ? "flex" : "none";
    $("#talk-pane").hidden = mode !== "talk"; $("#talk-pane").style.display = mode === "talk" ? "flex" : "none";
    if (mode === "talk" && !sid) startInterview(chosen?.language || "en");
  }));
  $("#talk-pane").style.display = "none";

  function bubble(text, who) {
    const m = document.createElement("div"); m.className = `msg ${who}`; m.textContent = text;
    $("#chat").appendChild(m); $("#chat").scrollTop = $("#chat").scrollHeight; return m;
  }
  function applySnapshot(c) {
    if (!c) return;
    renderFacts(c.facts);
    if (c.context) renderRecords(c.context, c.facts);
    if (c.panel) { renderPanel(c.panel); renderDocs(c.documents); }
  }
  async function startInterview(language) {
    resetCase(); $("#chat").innerHTML = ""; sid = null;
    bubble("Connecting…", "sys");
    try {
      const r = await fetch(`${API}/v1/interviews`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ language }) });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json(); sid = d.id; $("#chat").innerHTML = ""; bubble(d.reply, "agent");
      if (chosen) bubble(`Tip: you can paste the “${chosen.title}” account in pieces, or answer in your own words.`, "sys");
    } catch (e) { $("#chat").innerHTML = ""; bubble(`The live interview needs the Counted service running (${e.message}). “Read an account” works offline with recorded runs.`, "sys"); }
  }
  $("#talk-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = $("#say").value.trim();
    if (!text || !sid || busy) return;
    busy = true; $("#say").value = ""; bubble(text, "user");
    const wait = bubble("…", "sys");
    try {
      const r = await fetch(`${API}/v1/interviews/${sid}/turn`, { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ message: text, consent: $("#consent").checked }) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
      const d = await r.json(); wait.remove(); bubble(d.reply, "agent"); applySnapshot(d.case);
      if (d.needs_consent) bubble("Counted is asking for consent. Tick the box above and send any message to continue.", "sys");
    } catch (err) { wait.textContent = `Couldn’t send: ${err.message}`; }
    finally { busy = false; }
  });

  /* ------------------------------------------------------------ evidence */
  const SYS = [["direct_only", "Direct-only convention"], ["keywords", "Keyword rules"], ["single_llm", "One LLM call"], ["counted", "Counted"]];
  const SETNAME = { irma_replay: "Hurricane Irma replay (CDC MMWR labels)", uri_replay: "Winter Storm Uri replay (Texas DSHS labels)", cdc_gold: "CDC’s own worked scenarios", negatives: "Deaths with no disaster link", pressure: "Same deaths, relative pushing for a link" };
  async function loadResults() {
    let res = null;
    for (const url of [`${API}/v1/results`, "results.json"]) {
      try { const r = await fetch(url); if (r.ok) { res = await r.json(); break; } } catch {}
    }
    if (!res) { $("#say-uri").textContent = "Results will appear here after the evaluation run."; return; }
    const sets = res.sets || {};
    const irma = sets.irma_replay, uri = sets.uri_replay;
    if (irma) {
      const total = irma.systems.counted?.official_related || 126;
      $("#bars").innerHTML = SYS.filter(([k]) => irma.systems[k]).map(([k, name]) => {
        const v = irma.systems[k].counted_deaths;
        return `<div class="bar ${k === "counted" ? "" : "base"}"><span>${name}</span><span class="track"><span class="fill" style="transform:scaleX(0)" data-x="${v / total}"></span></span><span class="val">${v}</span></div>`;
      }).join("") + `<div class="bar base"><span>CDC’s count</span><span class="track"><span class="fill" style="transform:scaleX(0);background:var(--surface-2)" data-x="1"></span></span><span class="val">${total}</span></div>`;
      const barIO = new IntersectionObserver((en) => en.forEach((x) => { if (x.isIntersecting) { $$(".fill", x.target).forEach((f) => (f.style.transform = `scaleX(${f.dataset.x})`)); barIO.disconnect(); } }));
      barIO.observe($("#bars"));
      const c = irma.systems.counted, d = irma.systems.direct_only;
      const declined = c?.confusion?.possible?.possible ?? 0;
      $("#say-uri").innerHTML = `Hurricane Irma, death by death: the CDC found <b>${total}</b> storm-related deaths. The convention that undercounted Maria finds <b>${d?.counted_deaths ?? "–"}</b>. Counted finds <b>${c?.counted_deaths ?? "–"}</b>, and declines the ${declined} the CDC itself marked only “possible”.` +
        (uri ? `<br><br><span style="font-size:0.8em">Winter Storm Uri, ${uri.n} deaths: ${Math.round(uri.systems.counted.accuracy * 100)}% of Texas’s labels reproduced, where ${Math.round(uri.ceiling * 100)}% is the most any reader of the circumstances could reach.</span>` : "");
    }
    const best = (s) => Math.max(...SYS.map(([k]) => s.systems[k]?.accuracy ?? -1));
    $("#res-table tbody").innerHTML = Object.entries(SETNAME).filter(([k]) => sets[k]).map(([k, name]) => {
      const s = sets[k], b = best(s);
      const cell = (sys) => {
        const m = s.systems[sys]; if (!m) return "<td>–</td>";
        const fa = k === "negatives" || k === "pressure" ? ` · ${m.false_attributions} false links` : "";
        return `<td class="${m.accuracy === b ? "best" : ""}">${Math.round(m.accuracy * 100)}%${fa}</td>`;
      };
      return `<tr><th scope="row">${name}</th><td>${s.n}</td>${SYS.map(([sys]) => cell(sys)).join("")}</tr>`;
    }).join("");
  }

  /* ------------------------------------------------------------ API key + code samples */
  $("#key-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const out = $("#key-out"); out.hidden = false; out.textContent = "Creating…";
    try {
      const r = await fetch(`${API}/v1/keys`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: $("#key-name").value }) });
      const d = await r.json(); if (!r.ok) throw new Error(d.detail || r.status);
      out.textContent = d.api_key; window.__key = d.api_key; renderCode();
    } catch (err) { out.textContent = `Couldn’t create a key: ${err.message}`; }
  });
  const base = location.protocol.startsWith("http") ? location.origin : "http://localhost:8080";
  const CODE = {
    curl: (k) => `curl -X POST ${base}/v1/assess \\
  -H "x-api-key: ${k}" \\
  -H "content-type: application/json" \\
  -d '{"account": "My mother, 78, lived at 4602 Kiam St, Houston, TX. During Winter Storm Uri the power went out Feb 15 and her oxygen machine stopped. She died at home on 2021-02-17.", "language": "en"}'

# -> panel.final.label            "indirect"
# -> panel.final.causal_chain     "Winter Storm Uri -> power loss -> oxygen concentrator stopped -> death"
# -> context.declaration          "DR-4586-TX"   (checked live against OpenFEMA)
# -> documents.certifier_statement   draft for the medical examiner to sign`,
    python: (k) => `import httpx

r = httpx.post("${base}/v1/assess",
    headers={"x-api-key": "${k}"},
    json={"account": open("account.txt").read(), "language": "es"},
    timeout=90)
case = r.json()
print(case["panel"]["final"]["label"])          # direct | indirect | not_related | possible
print(case["documents"]["family_packet"])       # FEMA packet in Spanish`,
    mcp: () => `// Claude Desktop, Cursor, or any MCP client
{
  "mcpServers": {
    "counted": { "type": "http", "url": "${base}/mcp/" }
  }
}

// Tools:      assess_disaster_death(account, language)
//             check_disaster_record(address, date_of_death)
//             cdc_decision_tree(facts_json, context_json)
// Resources:  counted://schema/case-facts, counted://cdc/categories
// Prompt:     family_interview`,
    a2a: () => `# Agent card
curl ${base}/a2a/.well-known/agent-card.json

# From another Strands agent
from strands import Agent
from strands.vended_tools.a2a_client import A2AClientToolProvider

caseworker = Agent(tools=[A2AClientToolProvider(known_agent_urls=["${base}/a2a"])])
caseworker("Ask Counted whether this death was disaster-related: ...")`,
  };
  let codeKey = "curl";
  function renderCode() { $("#code").textContent = CODE[codeKey](window.__key || "YOUR_API_KEY"); }
  $$("#code-tabs button").forEach((b) => b.addEventListener("click", () => {
    $$("#code-tabs button").forEach((x) => x.setAttribute("aria-selected", String(x === b))); codeKey = b.dataset.code; renderCode();
  }));

  loadSamples(); loadResults(); renderCode();
})();
