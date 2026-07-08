"use strict";

/* ---------- state ---------- */
const S = {
  library: { transcripts: [], folders: [], tags: [] },
  view: { type: "all", value: null },
  selectedId: null,
  ready: false,
  recording: false,
  devices: null,
  selOut: -1, selIn: -1,   // -1 = Auto (capture all devices)
  search: "",
  recStart: 0, recTimer: null,
  liveLast: null, liveEl: null,
};

const $ = (id) => document.getElementById(id);
const api = () => window.pywebview.api;

/* ---------- helpers ---------- */
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmtDur(sec) {
  if (sec == null) return "—";
  const m = Math.floor(sec / 60), s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}
function d2(n) { return String(n).padStart(2, "0"); }
function fmtTime(iso) {
  const d = new Date(iso); if (isNaN(d)) return "";
  let h = d.getHours(); const m = d2(d.getMinutes());
  const ap = h >= 12 ? "pm" : "am"; h = h % 12 || 12;
  return `${h}:${m} ${ap}`;
}
function dateGroup(iso) {
  const d = new Date(iso); if (isNaN(d)) return "Unknown";
  const now = new Date();
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diff = Math.round((today - day) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  return d.toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" });
}
function toast(msg) {
  const t = $("toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(t._t); t._t = setTimeout(() => t.classList.remove("show"), 2200);
}
const PALETTE = ["#0033CC", "#b8860b", "#8e44ad", "#c0392b", "#16a085", "#d35400"];
function speakerColor(label) {
  if (label === "Me") return "#0a7d2c";
  if (label === "Them") return "#0033CC";
  const m = /Speaker (\d+)/.exec(label);
  return m ? PALETTE[(parseInt(m[1], 10) - 1) % PALETTE.length] : "#0033CC";
}
function copyText(text) {
  try {
    const p = navigator.clipboard && navigator.clipboard.writeText(text);
    if (p && p.then) { p.catch(() => fallbackCopy(text)); return; }
  } catch (e) {}
  fallbackCopy(text);
}
function fallbackCopy(text) {
  const ta = document.createElement("textarea");
  ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.focus(); ta.select();
  try { document.execCommand("copy"); } catch (_) {}
  document.body.removeChild(ta);
}
function flashButton(btn, label) {
  if (!btn) return;
  const orig = btn.innerHTML;
  btn.innerHTML = label;
  btn.classList.add("flash");
  clearTimeout(btn._flash);
  btn._flash = setTimeout(() => { btn.innerHTML = orig; btn.classList.remove("flash"); }, 1400);
}

/* ---------- init ---------- */
let _inited = false;
function init() {
  if (_inited) return; _inited = true;
  bindUI();
  api().get_library().then(lib => { S.library = lib; renderSidebar(); renderList(); });
  loadDevices();   // device pills/modal don't need the model — show them right away
  pollStatus();
}
window.addEventListener("pywebviewready", init);
document.addEventListener("DOMContentLoaded", () => { if (window.pywebview) init(); });

function pollStatus() {
  api().get_status().then(s => {
    setStatusMsg(s.message);
    if (s.ready) { S.ready = true; $("startBtn").disabled = false; loadDevices(); }
    else setTimeout(pollStatus, 400);
  });
}
function setStatusMsg(msg) {
  if (!S.ready && msg && msg !== "ready")
    $("startBtn").innerHTML = `<span class="dot-red"></span> ${esc(msg)}`;
  else if (!S.recording)
    $("startBtn").innerHTML = `<span class="dot-red"></span> Start listening`;
}

/* ---------- push handlers (Python -> JS) ---------- */
window.onLibrary = (lib) => { S.library = lib; renderSidebar(); if (!S.recording) renderList(); };
window.onReady = (devices) => { S.ready = true; $("startBtn").disabled = false; setDevices(devices); };
window.onStatus = (msg) => setStatusMsg(msg);
window.onPhrase = (label, text) => appendLive(label, text);
window.onSaved = (entry) => finishRecording(entry);

/* ---------- devices ---------- */
function loadDevices() { api().get_devices().then(setDevices); }
function setDevices(dev) {
  if (!dev) return;
  S.devices = dev;
  const autoOpt = '<option value="-1">Auto — use whichever is active (recommended)</option>';
  const os = $("outSelect"), is = $("inSelect");
  os.innerHTML = autoOpt + dev.outputs.map((o, i) => `<option value="${i}">${esc(o.name)}</option>`).join("");
  is.innerHTML = autoOpt + dev.inputs.map((o, i) => `<option value="${i}">${esc(o.name)}</option>`).join("");
  os.value = String(S.selOut); is.value = String(S.selIn);
  $("devStatus").classList.toggle("ok", dev.outputs.length > 0 && dev.inputs.length > 0);
  $("devStatusText").textContent = dev.has_speaker_id
    ? "Ready — capturing all devices, speaker ID on" : "Ready — capturing all devices";
  setDevicePillsFromSel();
}

/* ---------- sidebar ---------- */
function renderSidebar() {
  const tagNav = $("tagNav");
  tagNav.innerHTML = (S.library.tags || []).map(t =>
    `<button class="nav-item" data-view="tag" data-value="${esc(t)}">
       <span class="chip-dot"></span><span>${esc(t)}</span></button>`).join("") ||
    `<div class="pill" style="border:none;color:var(--n400)">No tags yet</div>`;
  const folderNav = $("folderNav");
  folderNav.innerHTML = (S.library.folders || []).map(f =>
    `<button class="nav-item" data-view="folder" data-value="${esc(f)}">
       <svg viewBox="0 0 24 24" class="ico"><path d="M3 7h6l2 2h10v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/></svg>
       <span>${esc(f)}</span></button>`).join("") ||
    `<div class="pill" style="border:none;color:var(--n400)">No folders yet</div>`;
  document.querySelectorAll("#nav .nav-item").forEach(b => {
    const match = b.dataset.view === S.view.type &&
      (b.dataset.value || null) === (S.view.value || null);
    b.classList.toggle("active", match);
  });
}

function setView(type, value) {
  S.view = { type, value: value || null };
  S.search = ""; $("searchBar").classList.add("hidden"); $("searchInput").value = "";
  closeDetail();
  const titles = { all: "All transcripts", favourites: "Favourites",
    tag: "#" + (value || ""), folder: value || "" };
  $("pageTitle").textContent = titles[type] || "Transcripts";
  renderSidebar(); renderList();
}

/* ---------- list ---------- */
function visibleItems() {
  let items = (S.library.transcripts || []).slice();
  if (S.view.type === "favourites") items = items.filter(t => t.favourite);
  else if (S.view.type === "tag") items = items.filter(t => (t.tags || []).includes(S.view.value));
  else if (S.view.type === "folder") items = items.filter(t => t.folder === S.view.value);
  return items;
}
function renderList() {
  renderCards(visibleItems());
}
function renderCards(items) {
  const panel = $("listPanel");
  if (!items.length) { panel.innerHTML = `<div class="empty">No transcripts here yet.</div>`; return; }
  let html = "", lastGroup = null;
  for (const t of items) {
    const g = dateGroup(t.created);
    if (g !== lastGroup) { html += `<div class="date-group">${esc(g)}</div>`; lastGroup = g; }
    const tags = (t.tags || []).map(x => `<span class="tagpill">${esc(x)}</span>`).join("");
    html += `<div class="card ${t.id === S.selectedId ? "sel" : ""}" data-id="${t.id}">
      <div class="card-actions">
        <button class="btn-icon" data-act="copy" title="Copy">⧉</button>
        <button class="btn-icon" data-act="move" title="Move to folder">🗂</button>
        <button class="btn-icon star ${t.favourite ? "on" : ""}" data-act="fav" title="Favourite">★</button>
        <button class="btn-icon" data-act="del" title="Remove from library">🗑</button>
      </div>
      <p class="card-title">${esc(t.title)}</p>
      <p class="card-preview">${esc(t.preview || "")}</p>
      <div class="card-meta">
        <span>${esc(fmtTime(t.created))}</span>
        <span>·</span><span>${fmtDur(t.duration_seconds)}</span>
        ${tags ? `<span>·</span>${tags}` : ""}
      </div>
    </div>`;
  }
  panel.innerHTML = html;
}

/* ---------- detail ---------- */
function openDetail(tid) {
  api().get_transcript(tid).then(res => {
    if (!res) return;
    S.selectedId = tid;
    $("livePanel").classList.add("hidden");
    document.querySelector(".body").classList.add("detail-open");
    $("detailPanel").classList.remove("hidden");
    renderDetail(res);
    renderList();
  });
}
function closeDetail() {
  S.selectedId = null;
  document.querySelector(".body").classList.remove("detail-open");
  $("detailPanel").classList.add("hidden");
}
function renderDetail(res) {
  const t = res.meta;
  const bubbles = (res.messages || []).map(m =>
    `<div class="bubble ${m.who === "me" ? "me" : "them"}">${esc(m.text)}</div>`).join("");
  const tags = (t.tags || []).map(x =>
    `<span class="tagpill">${esc(x)}<button data-tag="${esc(x)}" title="Remove">×</button></span>`).join("");
  $("detailPanel").innerHTML = `
    <button class="detail-back" id="detailBack">
      <svg viewBox="0 0 24 24" class="ico"><path d="M15 18l-6-6 6-6"/></svg> Back</button>
    <input class="detail-title" id="detailTitle" value="${esc(t.title)}">
    <div class="detail-sub">${esc(dateGroup(t.created))} · ${esc(fmtTime(t.created))} · ${fmtDur(t.duration_seconds)}</div>
    <div class="detail-tags" id="detailTags">${tags}
      <button class="tag-add" id="tagAdd">+ Add tag</button></div>
    <div class="actionbar">
      <button data-act="copy">⧉ Copy all</button>
      <button data-act="export">⬇ Export .txt</button>
      <button data-act="move">🗂 Move to folder</button>
      <button data-act="fav">${t.favourite ? "★ Favourited" : "☆ Favourite"}</button>
      <button data-act="del" class="danger">🗑 Remove</button>
    </div>
    <div class="chat">${bubbles || '<div class="empty">No speech in this transcript.</div>'}</div>`;
  $("detailBack").onclick = closeDetail;
  const titleEl = $("detailTitle");
  titleEl.onchange = () => api().set_title(t.id, titleEl.value).then(refresh);
  $("tagAdd").onclick = () => {
    const tag = prompt("Add tag:");
    if (tag) api().add_tag(t.id, tag).then(() => { refresh(); openDetail(t.id); });
  };
  $("detailTags").querySelectorAll("button[data-tag]").forEach(b =>
    b.onclick = () => api().remove_tag(t.id, b.dataset.tag).then(() => { refresh(); openDetail(t.id); }));
  $("detailPanel").querySelectorAll(".actionbar button").forEach(b =>
    b.onclick = () => detailAction(b.dataset.act, t, b));
}
function detailAction(act, t, btn) {
  if (act === "copy") api().get_transcript(t.id).then(r => { copyText(r.body || ""); flashButton(btn, "✓ Copied"); toast("Copied to clipboard"); });
  else if (act === "export") api().export_txt(t.id).then(r => {
    if (r && r.ok) toast("Exported"); else if (r && !r.cancelled) toast("Export failed"); });
  else if (act === "move") openFolderPop(t, btn);
  else if (act === "fav") api().toggle_favourite(t.id).then(() => { refresh(); openDetail(t.id); });
  else if (act === "del") removeItem(t);
}

/* ---------- card / detail shared actions ---------- */
function removeItem(t) {
  api().remove_from_library(t.id).then(r => {
    if (S.selectedId === t.id) closeDetail();
    refresh();
    toast("Removed from library — file kept on disk");
  });
}

/* ---------- move-to-folder popover ---------- */
function openFolderPop(t, anchor) {
  const pop = $("folderPop");
  const folders = S.library.folders || [];
  let html = folders.map(f =>
    `<button class="pop-item" data-folder="${esc(f)}">${esc(f)}
       ${t.folder === f ? '<span class="tick">✓</span>' : ""}</button>`).join("");
  if (t.folder) html += `<div class="pop-divider"></div>
     <button class="pop-item" data-folder="__none__">Remove from folder</button>`;
  html += `<div class="pop-divider"></div>
    <div class="pop-new"><input id="newFolderInput" placeholder="New folder..."><button id="newFolderBtn">Add</button></div>`;
  pop.innerHTML = html;
  const r = anchor.getBoundingClientRect();
  pop.style.top = Math.min(r.bottom + 6, window.innerHeight - 220) + "px";
  pop.style.left = Math.min(r.left, window.innerWidth - 240) + "px";
  pop.classList.remove("hidden");
  pop.querySelectorAll("button[data-folder]").forEach(b => b.onclick = () => {
    const f = b.dataset.folder === "__none__" ? null : b.dataset.folder;
    api().set_folder(t.id, f).then(() => {
      closePop(); refresh(); if (S.selectedId === t.id) openDetail(t.id);
      toast(f ? `Moved to ${f}` : "Removed from folder");
    });
  });
  $("newFolderBtn").onclick = () => {
    const name = $("newFolderInput").value.trim();
    if (!name) return;
    api().set_folder(t.id, name).then(() => {
      closePop(); refresh(); if (S.selectedId === t.id) openDetail(t.id);
      toast(`Moved to ${name}`);
    });
  };
}
function closePop() { $("folderPop").classList.add("hidden"); }

/* ---------- recording ---------- */
function startRecording() {
  if (!S.ready || S.recording) return;
  const title = $("recTitle").value;
  api().start(S.selOut, S.selIn, title).then(r => {
    if (!r || !r.ok) { toast("Could not start: " + ((r && r.error) || "audio error")); return; }
    S.recording = true;
    S.liveLast = null; S.liveEl = null;
    $("liveBody").innerHTML = "";
    $("topbarIdle").classList.add("hidden");
    $("topbarRec").classList.remove("hidden");
    $("searchBar").classList.add("hidden");
    closeDetail();
    $("listPanel").classList.add("hidden");
    $("livePanel").classList.remove("hidden");
    S.recStart = Date.now();
    $("recTimer").textContent = "00:00";
    S.recTimer = setInterval(tickTimer, 500);
    if (r.devices) {
      const dv = r.devices;
      toast(dv.auto
        ? `Listening on all devices (${dv.outputs} output${dv.outputs !== 1 ? "s" : ""}, ${dv.mics} mic${dv.mics !== 1 ? "s" : ""})`
        : "Listening");
    }
  });
}
function tickTimer() {
  const sec = Math.floor((Date.now() - S.recStart) / 1000);
  $("recTimer").textContent = `${d2(Math.floor(sec / 60))}:${d2(sec % 60)}`;
}
function appendLive(label, text) {
  const body = $("liveBody");
  const who = label === "Me" ? "me" : "them";   // side/colour conveys the speaker
  if (who === S.liveLast && S.liveEl) {
    S.liveEl.textContent += " " + text;          // coalesce same-speaker phrases
  } else {
    const b = document.createElement("div");
    b.className = "bubble " + who;
    b.textContent = text;
    body.appendChild(b);
    S.liveEl = b; S.liveLast = who;
  }
  body.scrollTop = body.scrollHeight;
}
function stopRecording() {
  if (!S.recording) return;
  $("stopBtn").disabled = true;
  $("stopBtn").textContent = "Saving...";
  api().stop($("recTitle").value);
}
function finishRecording(entry) {
  clearInterval(S.recTimer); S.recTimer = null;
  S.recording = false;
  $("topbarRec").classList.add("hidden");
  $("topbarIdle").classList.remove("hidden");
  $("livePanel").classList.add("hidden");
  $("listPanel").classList.remove("hidden");
  $("recTitle").value = "";
  $("stopBtn").disabled = false; $("stopBtn").textContent = "Stop listening";
  api().get_library().then(lib => {
    S.library = lib; renderSidebar();
    if (entry && entry.id) { setView("all"); openDetail(entry.id); toast("Transcript saved"); }
    else { renderList(); toast("No speech captured — nothing saved"); }
  });
}

/* ---------- search ---------- */
let _searchT = null;
function doSearch() {
  clearTimeout(_searchT);
  _searchT = setTimeout(() => {
    const q = $("searchInput").value.trim();
    if (!q) { renderList(); return; }
    api().search(q).then(items => renderCards(items));
  }, 140);
}

/* ---------- refresh ---------- */
function refresh() {
  return api().get_library().then(lib => {
    S.library = lib; renderSidebar();
    if ($("searchInput").value.trim()) doSearch(); else renderList();
  });
}

/* ---------- UI bindings ---------- */
function bindUI() {
  $("startBtn").onclick = startRecording;
  $("stopBtn").onclick = stopRecording;
  $("recTitle").addEventListener("input", () => api().set_pending_title($("recTitle").value));

  $("searchToggle").onclick = () => {
    const sb = $("searchBar"); sb.classList.toggle("hidden");
    if (!sb.classList.contains("hidden")) $("searchInput").focus();
  };
  $("searchClose").onclick = () => { $("searchBar").classList.add("hidden"); $("searchInput").value = ""; renderList(); };
  $("searchInput").addEventListener("input", doSearch);

  $("audioSettingsBtn").onclick = () => { $("audioModal").classList.remove("hidden"); loadDevices(); };
  $("audioClose").onclick = () => $("audioModal").classList.add("hidden");
  $("refreshDevices").onclick = () => api().get_devices().then(setDevices);
  $("outSelect").onchange = e => { S.selOut = parseInt(e.target.value, 10); setDevicePillsFromSel(); };
  $("inSelect").onchange = e => { S.selIn = parseInt(e.target.value, 10); setDevicePillsFromSel(); };

  // event delegation for nav
  $("nav").addEventListener("click", e => {
    const b = e.target.closest(".nav-item"); if (!b) return;
    setView(b.dataset.view, b.dataset.value);
  });
  // event delegation for cards
  $("listPanel").addEventListener("click", e => {
    const actBtn = e.target.closest("[data-act]");
    const card = e.target.closest(".card"); if (!card) return;
    const id = card.dataset.id;
    const t = (S.library.transcripts || []).find(x => x.id === id) || { id };
    if (actBtn) {
      e.stopPropagation();
      const a = actBtn.dataset.act;
      if (a === "copy") api().get_transcript(id).then(r => { copyText(r.body || ""); flashButton(actBtn, "✓"); toast("Copied to clipboard"); });
      else if (a === "fav") api().toggle_favourite(id).then(refresh);
      else if (a === "move") openFolderPop(t, actBtn);
      else if (a === "del") removeItem(t);
      return;
    }
    openDetail(id);
  });

  // Clicking on a non-text area (buttons, sidebar, empty space) clears any active
  // highlight. Chromium keeps the selection when you mousedown on a user-select:none
  // element, so we collapse it ourselves unless the click lands on selectable text.
  document.addEventListener("mousedown", e => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed) return;               // nothing highlighted
    const t = e.target;
    const us = t && t.nodeType === 1
      ? (getComputedStyle(t).webkitUserSelect || getComputedStyle(t).userSelect)
      : "";
    if (us !== "text") sel.removeAllRanges();           // clicked outside text -> unhighlight
  });

  document.addEventListener("keydown", e => { if (e.key === "Escape") { closePop(); if (S.selectedId) closeDetail(); } });
  document.addEventListener("click", e => {
    if (!e.target.closest("#folderPop") && !e.target.closest('[data-act="move"]')) closePop();
  });
}
function setDevicePillsFromSel() {
  const d = S.devices; if (!d) return;
  const outName = S.selOut < 0 ? "Auto (all outputs)" : (d.outputs[S.selOut] ? d.outputs[S.selOut].name : "—");
  const inName = S.selIn < 0 ? "Auto (all mics)" : (d.inputs[S.selIn] ? d.inputs[S.selIn].name : "—");
  $("devicePills").innerHTML =
    `<div class="pill" title="${esc(outName)}">🔊 ${esc(outName)}</div>` +
    `<div class="pill" title="${esc(inName)}">🎙 ${esc(inName)}</div>`;
}
