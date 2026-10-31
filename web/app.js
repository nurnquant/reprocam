// ReproCam UI. One flow for live runs and sample replays: open the event stream, add each event
// to the timeline, and reveal the matching artifact (test, results, evidence, ticket) from the
// run summary as its event arrives. ?sample=bug1&speed=4 starts a replay on load.

const $ = (id) => document.getElementById(id);
const state = { kind: null, id: null, summary: null, source: null, rows: new Map(), n: 0, t0: null, timer: null };

const STAGES = {
  frames: "Pull keyframes + audio",
  transcribe: "Transcribe the narration",
  understand: "Understand the recording",
  testgen: "Write the test",
  run: "Run on the buggy build",
  judge: "Judge the failure",
  fixcheck: "Run on the fixed build",
  segment: "Find the broken element",
  ticket: "File the ticket",
  error: "Run stopped",
};
const TOOLS = { frames: "ffmpeg", run: "pytest · Playwright", fixcheck: "pytest · Playwright", ticket: "ReproCam" };
const MODEL_NAMES = [
  [/muse-spark-open/, "Muse Spark Open"], [/muse-spark/, "Muse Spark"],
  [/voice-transcribe/, "Voice Transcribe"], [/sam-3/, "SAM 3.1"],
];
const PROVIDERS = { fireworks: "Fireworks", baseten: "Baseten", meta: "Meta Model API" };

// ---------- helpers ----------

const esc = (s) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
const fmtClock = (t) => `${String(Math.floor(t / 60)).padStart(2, "0")}:${(t % 60).toFixed(1).padStart(4, "0")}`;
const modelName = (m) => (MODEL_NAMES.find(([re]) => re.test(m || "")) || [null, m])[1];

function toast(msg, ms = 4200) {
  const el = $("toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (el.hidden = true), ms);
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `${r.status}`);
  return body;
}

async function refresh() {
  state.summary = await api(`/${state.kind}/${state.id}`);
  return state.summary;
}

// ---------- reset / start ----------

function reset(label) {
  state.source?.close();
  clearInterval(state.timer);
  Object.assign(state, { summary: null, rows: new Map(), n: 0, t0: null });
  $("timeline").replaceChildren();
  $("verdict").hidden = true;
  $("clock").textContent = fmtClock(0);
  $("filmstrip").replaceChildren();
  $("transcript").hidden = true;
  $("failure").textContent = "";
  $("code").innerHTML = '<span class="placeholder">The generated test appears here once it\'s written.</span>';
  for (const s of ["stamp-buggy", "stamp-fixed"]) $(s).dataset.state = "idle";
  $("board").innerHTML = '<p class="placeholder">After the bug is reproduced, SAM 3.1 boxes the candidates and Muse Spark picks the one the claim is about.</p>';
  $("sam-steps").hidden = true;
  $("evidence-replay").hidden = true;
  $("ticket").innerHTML = '<p class="placeholder">Filed only when the bug is reproduced.</p>';
  $("copy-ticket").hidden = true;
  $("fix-btn").disabled = true;
  $("foot-cost").textContent = "";
  $("vf-label").textContent = label;
}

function listen(url) {
  state.source = new EventSource(url);
  state.source.onmessage = (m) => onEvent(JSON.parse(m.data));
  state.source.addEventListener("done", (m) => { state.source.close(); onDone(JSON.parse(m.data)); });
  state.source.onerror = () => { if (state.source.readyState === EventSource.CLOSED) return; };
}

async function startReplay(id, speed = 1) {
  reset(`sample · ${id} · replay`);
  Object.assign(state, { kind: "samples", id });
  const s = await refresh();
  showVideo(s.video_url);
  const { events } = await api(`/samples/${id}/replay`, { method: "POST" });
  listen(`${events}?speed=${speed}`);
}

async function startUpload(file) {
  reset("uploading …");
  showVideo(URL.createObjectURL(file));
  const form = new FormData();
  form.append("video", file);
  try {
    const r = await api("/runs", { method: "POST", body: form });
    Object.assign(state, { kind: "runs", id: r.id });
    $("vf-label").textContent = `live run · ${r.id}`;
    toast(`Live run started. ${r.left_for_you} left for you today.`);
    listen(r.events);
  } catch (e) {
    $("vf-label").textContent = "not started";
    toast(e.message, 7000);
  }
}

function showVideo(src) {
  const v = $("video");
  $("empty").hidden = !!src;
  if (src) { v.src = src; v.load(); }
}

// ---------- events ----------

function tick(t) {
  const speed = Number(new URLSearchParams(location.search).get("speed") || 1);
  state.t0 = performance.now() - (t * 1000) / speed;
  if (!state.timer) {
    state.timer = setInterval(() => {
      $("clock").textContent = fmtClock(((performance.now() - state.t0) / 1000) * speed);
    }, 100);
  }
}

function badge(e) {
  if (e.stage === "segment" && e.status !== "start") {
    const pick = /Muse Spark/.test(e.detail) ? " → <b>Muse Spark Open</b> · Fireworks · effort low" : "";
    return `<b>SAM 3.1</b> · Meta Model API${pick}`;
  }
  if (e.model) {
    const parts = [`<b>${esc(modelName(e.model))}</b>`, esc(PROVIDERS[e.provider] || e.provider)];
    if (e.effort) parts.push(`effort ${esc(e.effort)}`);
    return parts.join(" · ");
  }
  return TOOLS[e.stage] ? `<b>${TOOLS[e.stage]}</b>` : "";
}

function row(e) {
  const key = e.status === "retry" ? `retry-${e.attempt}` : `${e.stage}-${e.attempt ?? 0}`;
  let li = state.rows.get(key);
  if (!li) {
    li = document.createElement("li");
    li.dataset.stage = e.stage;
    state.n += 1;
    const name = e.status === "retry" ? "Retry with the judge's feedback" : STAGES[e.stage] || e.stage;
    li.innerHTML = `<span class="num">${String(state.n).padStart(2, "0")}</span>
      <span class="name">${esc(name)}${e.attempt ? ` <small>· attempt ${e.attempt}</small>` : ""}</span>
      <span class="when"></span><span class="badge" hidden></span><span class="detail"></span>`;
    state.rows.set(key, li);
    $("timeline").append(li);
  }
  li.dataset.status = e.status;
  li.querySelector(".when").textContent = `+${e.t.toFixed(1)}s`;
  const b = badge(e);
  const bEl = li.querySelector(".badge");
  if (b) { bEl.innerHTML = b; bEl.hidden = false; }
  li.querySelector(".detail").textContent = e.detail || "";
  li.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

async function onEvent(e) {
  tick(e.t);
  row(e);
  const live = state.kind === "runs";
  const s = live && e.status !== "start" ? await refresh() : state.summary;
  const attempt = s.attempts.find((a) => a.name === `attempt_${e.attempt}`);

  if (e.stage === "frames" && e.status === "ok") renderFilmstrip(s);
  if (e.stage === "transcribe" && e.status === "ok" && s.transcript) {
    $("transcript-text").textContent = `“${s.transcript}”`;
    $("transcript").hidden = false;
  }
  if (e.stage === "understand" && e.status === "ok") markBugFrame(s);
  if (e.stage === "testgen" && e.status === "ok" && attempt) {
    renderCode(attempt.test_code);
    $("failure").textContent = "";
    stamp("stamp-buggy", "idle");
    stamp("stamp-fixed", "idle");
  }
  if (e.stage === "run") {
    if (e.status === "start") stamp("stamp-buggy", "running");
    else if (attempt?.buggy) {
      stamp("stamp-buggy", attempt.buggy.outcome === "pass" ? "pass" : "fail");
      $("failure").textContent = attempt.buggy.summary.replaceAll(" | ", "\n");
      highlightFailure(attempt.buggy.summary);
    }
  }
  if (e.stage === "fixcheck") stamp("stamp-fixed", e.status === "ok" ? "pass" : "fail");
  if (e.stage === "segment" && e.status === "ok" && s.segment) playEvidence(s.segment);
  if (e.stage === "ticket" && e.status === "ok" && s.ticket_md) renderTicket(s);
}

function onDone(result) {
  clearInterval(state.timer);
  state.timer = null;
  const v = $("verdict");
  const ok = result.verdict === "REPRODUCED";
  v.textContent = ok
    ? `Reproduced · attempt ${result.attempt} · fixed build ${result.fixcheck === "pass" ? "passes" : "fails"}`
    : `${(result.verdict || "error").replaceAll("_", " ")}${result.error ? ` · ${result.error}` : ""}`;
  v.classList.toggle("bad", !ok);
  v.hidden = false;
  $("fix-btn").disabled = !result.test;
  const cost = result.cost_usd != null ? `$${result.cost_usd.toFixed(4)} model cost` : "model cost n/a";
  $("foot-cost").textContent = state.kind === "samples"
    ? `original run: ${result.seconds}s · ${cost} · this replay: $0`
    : `${result.seconds}s · ${cost}`;
  if (state.kind === "samples") $("clock").textContent = fmtClock(result.seconds);
}

// ---------- recording ----------

function renderFilmstrip(s) {
  const strip = $("filmstrip");
  strip.replaceChildren(...s.keyframes.map((k) => {
    const f = document.createElement("figure");
    f.dataset.n = k.n;
    f.innerHTML = `<img src="${k.url}" alt="frame ${k.n}" loading="lazy"><figcaption>f${k.n} · ${k.t.toFixed(1)}s</figcaption>`;
    f.onclick = () => { $("video").currentTime = k.t; };
    return f;
  }));
}

function markBugFrame(s) {
  const ref = s.steps?.bug_claim?.frame_ref;
  for (const f of $("filmstrip").children) f.classList.toggle("bug", Number(f.dataset.n) === ref);
  const k = s.keyframes.find((x) => x.n === ref);
  if (k) $("video").currentTime = k.t;
}

// ---------- test ----------

const PY = /(#.*$)|((?:[frbFRB]{1,2})?("|')(?:\\.|(?!\3).)*\3)|\b(def|import|from|return|for|in|if|elif|else|assert|with|as|not|and|or|True|False|None|while|try|except|raise|lambda)\b|\b([A-Za-z_]\w*)(?=\()/g;

function renderCode(code) {
  $("code").innerHTML = code.replace(/\n$/, "").split("\n").map((line) => {
    const html = esc(line).replace(PY, (m, c, s, _q, k, f) =>
      c ? `<span class="c">${m}</span>` : s ? `<span class="s">${m}</span>` : k ? `<span class="k">${m}</span>` : `<span class="f">${m}</span>`);
    return `<span class="ln">${html || " "}</span>`;
  }).join("");
}

function highlightFailure(summary) {
  const first = summary.split(" | ")[0].trim();
  const lines = [...$("code").querySelectorAll(".ln")];
  const hit = lines.find((l) => first && l.textContent.includes(first.slice(0, 40)));
  lines.forEach((l) => l.classList.toggle("hit", l === hit));
  hit?.scrollIntoView({ block: "center", behavior: "smooth" });
}

function stamp(id, st) {
  const el = $(id);
  if (el.dataset.state === st) return;
  el.dataset.state = st;
  el.classList.remove("thump");
  void el.offsetWidth;
  if (st === "pass" || st === "fail") el.classList.add("thump");
}

// ---------- evidence: SAM proposes, Muse Spark decides ----------

function playEvidence(seg) {
  const cands = seg.candidates?.length ? seg.candidates : [seg.box];
  const chosen = seg.candidates?.length ? seg.picked : 0;
  const board = $("board");
  board.className = "board";
  board.innerHTML = `<div class="zoom"><div class="zoom-inner"><img alt="bug frame"></div></div>`;
  const inner = board.querySelector(".zoom-inner");
  const img = board.querySelector("img");
  const steps = $("sam-steps");
  steps.hidden = false;
  steps.querySelectorAll("li").forEach((li) => li.classList.remove("on"));
  $("evidence-replay").hidden = false;

  const tried = seg.tried?.find((t) => t.on_bug_frame) || seg.tried?.at(-1);
  $("sam-propose").textContent = seg.candidates?.length
    ? `${cands.length} boxes for “${seg.concept}”` + (seg.tried?.length > 1 ? ` (“${seg.tried[0].concept}” found none)` : "")
    : /SAM found nothing/.test(seg.method) ? "no boxes; Muse Spark located it instead" : `1 box for “${tried?.concept}”`;
  $("sam-decide").textContent = seg.candidates?.length ? `#${chosen}: ${seg.pick_reason}` : seg.method;

  img.onload = () => {
    const fw = img.naturalWidth, fh = img.naturalHeight;
    cands.forEach((b, i) => {
      const d = document.createElement("div");
      d.className = "cand" + (i === chosen ? " chosen" : "");
      const m = 5;  // SAM boxes hug the text; keep the border off the digits
      Object.assign(d.style, {
        left: `${((b.left - m) / fw) * 100}%`, top: `${((b.top - m) / fh) * 100}%`,
        width: `${((b.right - b.left + 2 * m) / fw) * 100}%`, height: `${((b.bottom - b.top + 2 * m) / fh) * 100}%`,
      });
      if (cands.length > 1) d.innerHTML = `<span>${i}</span>`;
      inner.append(d);
    });
    // Zoom: the 4:3 board first shows the whole frame, then fits the candidates (SAM proposes),
    // then dims all but the chosen box (Muse Spark decides). Borders stay thin via --s.
    const W = board.querySelector(".zoom").clientWidth, H = W * 0.75, d = W / fw;
    const view = (s, x0, y0) => `translate(${-x0 * d * s}px, ${-y0 * d * s}px) scale(${s})`;
    inner.style.transform = view(1, 0, -(H / d - fh) / 2);
    const pad = 40;
    const bx0 = Math.min(...cands.map((b) => b.left)) - pad, bx1 = Math.max(...cands.map((b) => b.right)) + pad;
    const by0 = Math.min(...cands.map((b) => b.top)) - pad, by1 = Math.max(...cands.map((b) => b.bottom)) + pad;
    const s = Math.max(1, Math.min(W / ((bx1 - bx0) * d), H / ((by1 - by0) * d), 6));
    const vw = W / (d * s), vh = H / (d * s);  // visible area in frame pixels
    const x0 = Math.max(0, Math.min((bx0 + bx1) / 2 - vw / 2, fw - vw));
    const y0 = Math.max(Math.min(0, (fh - vh) / 2), Math.min((by0 + by1) / 2 - vh / 2, fh - vh));

    setTimeout(() => { inner.style.setProperty("--s", s); inner.style.transform = view(s, x0, y0); }, 500);
    setTimeout(() => { board.classList.add("show-cands"); steps.children[0].classList.add("on"); }, 1700);
    setTimeout(() => { board.classList.add("decided"); steps.children[1].classList.add("on"); }, 3500);
  };
  img.src = seg.frame_url;
  $("evidence-replay").onclick = () => playEvidence(seg);
}

// ---------- ticket ----------

function inlineMd(s, base) {
  return esc(s)
    .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, src) => `<img alt="${alt}" src="${/^(https?:|\/)/.test(src) ? src : base + src}">`)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
}

function renderMd(md, base) {
  const out = [];
  let list = null, code = null;
  for (const line of md.split("\n")) {
    if (code !== null) {
      if (line.startsWith("```")) { out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`); code = null; }
      else code.push(line);
      continue;
    }
    if (line.startsWith("```")) { code = []; continue; }
    const li = line.match(/^\d+\.\s+(.*)/);
    if (li) { if (!list) { list = []; } list.push(`<li>${inlineMd(li[1], base)}</li>`); continue; }
    if (list) { out.push(`<ol>${list.join("")}</ol>`); list = null; }
    const h = line.match(/^(#{1,3})\s+(.*)/);
    if (h) out.push(`<h${h[1].length}>${inlineMd(h[2], base)}</h${h[1].length}>`);
    else if (line.trim()) out.push(`<p>${inlineMd(line, base)}</p>`);
  }
  if (list) out.push(`<ol>${list.join("")}</ol>`);
  return out.join("\n");
}

function renderTicket(s) {
  $("ticket").innerHTML = renderMd(s.ticket_md, s.files_base);
  $("copy-ticket").hidden = false;
  $("copy-ticket").onclick = async () => {
    await navigator.clipboard.writeText(s.ticket_md);
    toast("Ticket markdown copied.");
  };
}

// ---------- buttons ----------

async function loadSamples() {
  const samples = await api("/samples");
  $("sample-menu").replaceChildren(...samples.map((s) => {
    const li = document.createElement("li");
    li.innerHTML = `<button><span class="id">${esc(s.id)} · ${esc(s.bug_id || "")}</span>${esc(s.title)}</button>`;
    li.querySelector("button").onclick = () => { toggleMenu(false); startReplay(s.id); };
    return li;
  }));
}

function toggleMenu(open) {
  $("sample-menu").hidden = !open;
  $("sample-btn").setAttribute("aria-expanded", String(open));
}

$("sample-btn").onclick = (ev) => { ev.stopPropagation(); toggleMenu($("sample-menu").hidden); };
document.addEventListener("click", () => toggleMenu(false));
$("upload").onchange = (ev) => { const f = ev.target.files[0]; if (f) startUpload(f); ev.target.value = ""; };

$("fix-btn").onclick = async () => {
  const btn = $("fix-btn");
  btn.disabled = true;
  stamp("stamp-fixed", "running");
  try {
    const r = await api(`/${state.kind}/${state.id}/fixcheck`, { method: "POST" });
    stamp("stamp-fixed", r.outcome === "pass" ? "pass" : "fail");
    toast(r.outcome === "pass"
      ? `Same test on the fixed build: passes (${r.seconds}s, no model calls).`
      : `Same test on the fixed build: ${r.outcome}. ${r.summary}`, 6000);
  } catch (e) {
    stamp("stamp-fixed", "idle");
    toast(e.message);
  }
  btn.disabled = false;
};

loadSamples().then(() => {
  const q = new URLSearchParams(location.search);
  if (q.get("sample")) startReplay(q.get("sample"), Number(q.get("speed") || 1));
}).catch((e) => toast(`Can't reach the ReproCam API: ${e.message}`));
