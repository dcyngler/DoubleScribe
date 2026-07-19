"use strict";

/* ---------- state ---------- */
const S = {
  library: { transcripts: [], folders: [], tags: [] },
  view: { type: "all", value: null },
  lang: "en",
  selectedId: null,
  detailFullscreen: false,
  ready: false,
  recording: false,
  consentAcknowledged: false,
  devices: null,
  selOut: -1, selIn: -1,   // -1 = Auto (capture all devices)
  search: "",
  filters: { tags: [], folder: "", favourite: false, dateFrom: "", dateTo: "", durMin: "", durMax: "", sort: "newest" },
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
  const d = new Date(iso); if (isNaN(d)) return t("dategroup_unknown");
  const now = new Date();
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diff = Math.round((today - day) / 86400000);
  if (diff === 0) return t("dategroup_today");
  if (diff === 1) return t("dategroup_yesterday");
  try {
    return d.toLocaleDateString(S.lang, { day: "numeric", month: "short", year: "numeric" });
  } catch (e) {
    return d.toLocaleDateString("en", { day: "numeric", month: "short", year: "numeric" });
  }
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

/* ---------- i18n ---------- */
function applyI18n() {
  const rtl = !!(window.I18N_RTL && window.I18N_RTL[S.lang]);
  document.documentElement.lang = S.lang;
  document.documentElement.dir = rtl ? "rtl" : "ltr";
  document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(el => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  document.querySelectorAll("[data-i18n-title]").forEach(el => { el.title = t(el.dataset.i18nTitle); });
  const p1 = $("consentP1"), p2 = $("consentP2");
  if (p1) p1.innerHTML = tHtml("consent_p1");
  if (p2) p2.innerHTML = tHtml("consent_p2");
  const op1 = $("onboardP1"), op2 = $("onboardP2");
  if (op1) op1.innerHTML = tHtml("onboard_p1");
  if (op2) op2.innerHTML = tHtml("onboard_p2");
  const langSel = $("settingsLanguage");
  if (langSel) {
    langSel.innerHTML = (window.I18N_LANGS || []).map(l =>
      `<option value="${l.code}"${l.code === S.lang ? " selected" : ""}>${esc(l.name)}</option>`).join("");
  }
  refreshDynamicI18n();
}
function refreshDynamicI18n() {
  const titles = { all: t("nav_all"), favourites: t("nav_favourites"),
    tag: "#" + (S.view.value || ""), folder: S.view.value || "" };
  $("pageTitle").textContent = titles[S.view.type] || t("pagetitle_transcripts_fallback");
  renderSidebar();
  if (!S.recording) renderList();
  if (S.selectedId) openDetail(S.selectedId);
  if (S.devices) setDevices(S.devices);
  setDevicePillsFromSel();
  if (!S.ready) setStatusMsg(S._lastStatusMsg);
}
function setLanguage(code) {
  S.lang = code;
  api().set_language(code);
  applyI18n();
}

/* ---------- init ---------- */
let _inited = false;
function init() {
  if (_inited) return; _inited = true;
  api().get_settings().then(s => {
    S.lang = s.language || "en";
    applyI18n();
    bindUI();
    api().get_library().then(lib => { S.library = lib; renderSidebar(); renderList(); });
    loadDevices();   // device pills/modal don't need the model — show them right away
    pollStatus();
    S.consentAcknowledged = !!s.consent_acknowledged;
    if (!s.onboarded) $("onboardModal").classList.remove("hidden");
    else maybeShowConsent();
    api().check_whats_new().then(info => { if (info) showReleaseNotes(info); });
  });
  $("updateLink").addEventListener("click", (e) => {
    e.preventDefault();
    if (e.currentTarget._url) api().open_url(e.currentTarget._url);
  });
  api().get_version().then(v => { $("statusbarVersion").textContent = `Double Scribe v${v}`; });
}

function maybeShowConsent() {
  if (!S.consentAcknowledged) $("consentModal").classList.remove("hidden");
}

function showReleaseNotes(info) {
  $("releaseNotesTitle").textContent = `${t("modal_whatsnew_title")} v${info.version}`;
  $("releaseNotesList").innerHTML = info.notes.map(n => `<li>${esc(n)}</li>`).join("");
  $("releaseNotesModal").classList.remove("hidden");
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
  S._lastStatusMsg = msg;
  if (!S.ready && msg && msg !== "ready")
    $("startBtn").innerHTML = `<span class="dot-red"></span> ${esc(msg)}`;
  else if (!S.recording)
    $("startBtn").innerHTML = `<span class="dot-red"></span> <span data-i18n="btn_start_listening">${esc(t("btn_start_listening"))}</span>`;
}

/* ---------- push handlers (Python -> JS) ---------- */
window.onLibrary = (lib) => { S.library = lib; renderSidebar(); if (!S.recording) renderList(); };
window.onReady = (devices) => { S.ready = true; $("startBtn").disabled = false; setDevices(devices); };
window.onStatus = (msg) => setStatusMsg(msg);
window.onPhrase = (label, text, voiceChange) => appendLive(label, text, voiceChange);
window.onSaved = (entry) => finishRecording(entry);
window.onUpdateAvailable = (info) => {
  const link = $("updateLink");
  $("updateVersion").textContent = `v${info.version}`;
  link._url = info.url;
  link.classList.remove("hidden");
};

/* ---------- devices ---------- */
function loadDevices() { api().get_devices().then(setDevices); }
function loadAppSettings() {
  api().get_version().then(v => { $("settingsVersion").textContent = `v${v}`; });
  api().get_settings().then(s => { $("profanityToggle").checked = !!s.profanity_filter; });
}
function setDevices(dev) {
  if (!dev) return;
  S.devices = dev;
  const autoOpt = `<option value="-1">${esc(t("option_auto_device"))}</option>`;
  const os = $("outSelect"), is = $("inSelect");
  os.innerHTML = autoOpt + dev.outputs.map((o, i) => `<option value="${i}">${esc(o.name)}</option>`).join("");
  is.innerHTML = autoOpt + dev.inputs.map((o, i) => `<option value="${i}">${esc(o.name)}</option>`).join("");
  os.value = String(S.selOut); is.value = String(S.selIn);
  $("devStatus").classList.toggle("ok", dev.outputs.length > 0 && dev.inputs.length > 0);
  $("devStatusText").textContent = dev.has_voice_split
    ? t("status_ready_voice_split") : t("status_ready");
  setDevicePillsFromSel();
}

/* ---------- sidebar ---------- */
function renderSidebar() {
  const tagNav = $("tagNav");
  tagNav.innerHTML = (S.library.tags || []).map(tag =>
    `<button class="nav-item" data-view="tag" data-value="${esc(tag)}">
       <span class="chip-dot"></span><span>${esc(tag)}</span></button>`).join("") ||
    `<div class="pill" style="border:none;color:var(--n400)">${esc(t("nav_no_tags"))}</div>`;
  const folderNav = $("folderNav");
  folderNav.innerHTML = (S.library.folders || []).map(f =>
    `<button class="nav-item" data-view="folder" data-value="${esc(f)}">
       <svg viewBox="0 0 24 24" class="ico"><path d="M3 7h6l2 2h10v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/></svg>
       <span>${esc(f)}</span></button>`).join("") ||
    `<div class="pill" style="border:none;color:var(--n400)">${esc(t("nav_no_folders"))}</div>`;
  document.querySelectorAll("#nav .nav-item").forEach(b => {
    const match = b.dataset.view === S.view.type &&
      (b.dataset.value || null) === (S.view.value || null);
    b.classList.toggle("active", match);
  });
}

function setView(type, value) {
  S.view = { type, value: value || null };
  S.search = ""; $("searchBar").classList.add("hidden"); $("searchInput").value = ""; resetFilters();
  closeDetail();
  const titles = { all: t("nav_all"), favourites: t("nav_favourites"),
    tag: "#" + (value || ""), folder: value || "" };
  $("pageTitle").textContent = titles[type] || t("pagetitle_transcripts_fallback");
  renderSidebar(); renderList();
}

/* ---------- list ---------- */
function visibleItems() {
  let items = (S.library.transcripts || []).slice();
  if (S.view.type === "favourites") items = items.filter(tr => tr.favourite);
  else if (S.view.type === "tag") items = items.filter(tr => (tr.tags || []).includes(S.view.value));
  else if (S.view.type === "folder") items = items.filter(tr => tr.folder === S.view.value);
  return items;
}
function renderList() {
  renderCards(visibleItems());
}
function renderCards(items) {
  const panel = $("listPanel");
  if (!items.length) { panel.innerHTML = `<div class="empty">${esc(t("empty_no_transcripts"))}</div>`; return; }
  let html = "", lastGroup = null;
  for (const tr of items) {
    const g = dateGroup(tr.created);
    if (g !== lastGroup) { html += `<div class="date-group">${esc(g)}</div>`; lastGroup = g; }
    const tags = (tr.tags || []).map(x => `<span class="tagpill">${esc(x)}</span>`).join("");
    html += `<div class="card ${tr.id === S.selectedId ? "sel" : ""}" data-id="${tr.id}">
      <div class="card-actions">
        <button class="btn-icon" data-act="copy" title="${esc(t("title_copy"))}">⧉</button>
        <button class="btn-icon" data-act="move" title="${esc(t("title_move_to_folder"))}"><img class="folder-ico" src="folder-icon.png" alt=""></button>
        <button class="btn-icon star ${tr.favourite ? "on" : ""}" data-act="fav" title="${esc(t("title_favourite"))}">★</button>
        <button class="btn-icon" data-act="del" title="${esc(t("title_remove_from_library"))}">🗑</button>
      </div>
      <p class="card-title">${esc(tr.title)}</p>
      <p class="card-preview">${esc(tr.preview || "")}</p>
      <div class="card-meta">
        <span>${esc(fmtTime(tr.created))}</span>
        <span>·</span><span>${fmtDur(tr.duration_seconds)}</span>
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
  setDetailFullscreen(false);
  document.querySelector(".body").classList.remove("detail-open");
  $("detailPanel").classList.add("hidden");
}
function setDetailFullscreen(on) {
  S.detailFullscreen = on;
  $("app").classList.toggle("detail-fs", on);
  const btn = $("detailFullscreen"); if (!btn) return;
  btn.title = on ? t("title_exit_full_screen") : t("title_full_screen");
  btn.innerHTML = on
    ? `<svg viewBox="0 0 24 24" class="ico"><polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/><line x1="14" y1="10" x2="21" y2="3"/><line x1="3" y1="21" x2="10" y2="14"/></svg>`
    : `<svg viewBox="0 0 24 24" class="ico"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>`;
}
function renderDetail(res) {
  const meta = res.meta;
  const bubbles = (res.messages || []).map(m =>
    `<div class="bubble ${m.who === "me" ? "me" : "them"}">${esc(m.text)}</div>`).join("");
  const tags = (meta.tags || []).map(x =>
    `<span class="tagpill">${esc(x)}<button data-tag="${esc(x)}" title="${esc(t("btn_remove"))}">×</button></span>`).join("");
  $("detailPanel").innerHTML = `
    <div class="detail-top">
      <button class="detail-back" id="detailBack">
        <svg viewBox="0 0 24 24" class="ico"><path d="M15 18l-6-6 6-6"/></svg> ${esc(t("detail_back"))}</button>
      <button class="detail-fullscreen" id="detailFullscreen" title="${esc(t("title_full_screen"))}"></button>
    </div>
    <input class="detail-title" id="detailTitle" value="${esc(meta.title)}">
    <div class="detail-sub">${esc(dateGroup(meta.created))} · ${esc(fmtTime(meta.created))} · ${fmtDur(meta.duration_seconds)}</div>
    <div class="detail-tags" id="detailTags">${tags}
      <button class="tag-add" id="tagAdd">+ ${esc(t("btn_add_tag"))}</button></div>
    <div class="actionbar">
      <button data-act="copy">⧉ ${esc(t("btn_copy_all"))}</button>
      <button data-act="export">⬇ ${esc(t("btn_export_txt"))}</button>
      <button data-act="move"><img class="folder-ico" src="folder-icon.png" alt=""> ${esc(t("title_move_to_folder"))}</button>
      <button data-act="fav">${meta.favourite ? "★ " + esc(t("btn_favourited")) : "☆ " + esc(t("btn_favourite"))}</button>
      <button data-act="del" class="danger">🗑 ${esc(t("btn_remove"))}</button>
    </div>
    <div class="chat">${bubbles || `<div class="empty">${esc(t("empty_no_speech"))}</div>`}</div>`;
  $("detailBack").onclick = closeDetail;
  $("detailFullscreen").onclick = () => setDetailFullscreen(!S.detailFullscreen);
  setDetailFullscreen(!!S.detailFullscreen);
  const titleEl = $("detailTitle");
  titleEl.onchange = () => api().set_title(meta.id, titleEl.value).then(refresh);
  $("tagAdd").onclick = () => {
    const tag = prompt(t("prompt_add_tag"));
    if (tag) api().add_tag(meta.id, tag).then(() => { refresh(); openDetail(meta.id); });
  };
  $("detailTags").querySelectorAll("button[data-tag]").forEach(b =>
    b.onclick = () => api().remove_tag(meta.id, b.dataset.tag).then(() => { refresh(); openDetail(meta.id); }));
  $("detailPanel").querySelectorAll(".actionbar button").forEach(b =>
    b.onclick = () => detailAction(b.dataset.act, meta, b));
}
function detailAction(act, meta, btn) {
  if (act === "copy") api().get_transcript(meta.id).then(r => { copyText(r.body || ""); flashButton(btn, "✓ " + t("toast_copied")); toast(t("toast_copied")); });
  else if (act === "export") api().export_txt(meta.id).then(r => {
    if (r && r.ok) toast(t("toast_exported")); else if (r && !r.cancelled) toast(t("toast_export_failed")); });
  else if (act === "move") openFolderPop(meta, btn);
  else if (act === "fav") api().toggle_favourite(meta.id).then(() => { refresh(); openDetail(meta.id); });
  else if (act === "del") removeItem(meta);
}

/* ---------- card / detail shared actions ---------- */
function removeItem(tr) {
  api().remove_from_library(tr.id).then(r => {
    if (S.selectedId === tr.id) closeDetail();
    refresh();
    toast(t("toast_removed_from_library"));
  });
}

/* ---------- move-to-folder popover ---------- */
function openFolderPop(tr, anchor) {
  const pop = $("folderPop");
  const folders = S.library.folders || [];
  let html = folders.map(f =>
    `<button class="pop-item" data-folder="${esc(f)}">${esc(f)}
       ${tr.folder === f ? '<span class="tick">✓</span>' : ""}</button>`).join("");
  if (tr.folder) html += `<div class="pop-divider"></div>
     <button class="pop-item" data-folder="__none__">${esc(t("popover_remove_from_folder"))}</button>`;
  html += `<div class="pop-divider"></div>
    <div class="pop-new"><input id="newFolderInput" placeholder="${esc(t("placeholder_new_folder"))}"><button id="newFolderBtn">${esc(t("btn_add"))}</button></div>`;
  pop.innerHTML = html;
  const r = anchor.getBoundingClientRect();
  pop.style.top = Math.min(r.bottom + 6, window.innerHeight - 220) + "px";
  pop.style.left = Math.min(r.left, window.innerWidth - 240) + "px";
  pop.classList.remove("hidden");
  pop.querySelectorAll("button[data-folder]").forEach(b => b.onclick = () => {
    const f = b.dataset.folder === "__none__" ? null : b.dataset.folder;
    api().set_folder(tr.id, f).then(() => {
      closePop(); refresh(); if (S.selectedId === tr.id) openDetail(tr.id);
      toast(f ? t("toast_moved_to", { folder: f }) : t("toast_removed_from_folder"));
    });
  });
  $("newFolderBtn").onclick = () => {
    const name = $("newFolderInput").value.trim();
    if (!name) return;
    api().set_folder(tr.id, name).then(() => {
      closePop(); refresh(); if (S.selectedId === tr.id) openDetail(tr.id);
      toast(t("toast_moved_to", { folder: name }));
    });
  };
}
function closePop() { $("folderPop").classList.add("hidden"); }

/* ---------- recording ---------- */
function startRecording() {
  if (!S.ready || S.recording) return;
  if (!S.consentAcknowledged) { $("consentModal").classList.remove("hidden"); return; }
  const title = $("recTitle").value;
  api().start(S.selOut, S.selIn, title).then(r => {
    if (!r || !r.ok) { toast(t("toast_could_not_start", { error: (r && r.error) || t("text_audio_error") })); return; }
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
      toast(dv.auto ? t("toast_listening_devices", { outputs: dv.outputs, mics: dv.mics }) : t("toast_listening"));
    }
  });
}
function tickTimer() {
  const sec = Math.floor((Date.now() - S.recStart) / 1000);
  $("recTimer").textContent = `${d2(Math.floor(sec / 60))}:${d2(sec % 60)}`;
}
function appendLive(label, text, voiceChange) {
  const body = $("liveBody");
  const who = label === "Me" ? "me" : "them";   // side/colour conveys the speaker
  if (who === S.liveLast && S.liveEl && !voiceChange) {
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
  $("stopBtn").textContent = t("text_saving");
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
  $("stopBtn").disabled = false; $("stopBtn").textContent = t("btn_stop_listening");
  api().get_library().then(lib => {
    S.library = lib; renderSidebar();
    if (entry && entry.id) { setView("all"); openDetail(entry.id); toast(t("toast_transcript_saved")); }
    else { renderList(); toast(t("toast_no_speech_captured")); }
  });
}

/* ---------- search ---------- */
function filtersActive() {
  const f = S.filters;
  return f.tags.length > 0 || !!f.folder || f.favourite || !!f.dateFrom || !!f.dateTo ||
    !!f.durMin || !!f.durMax || f.sort !== "newest";
}
function filterPayload() {
  const f = S.filters;
  return {
    tags: f.tags, folder: f.folder || null, favourite: f.favourite,
    date_from: f.dateFrom || null, date_to: f.dateTo || null,
    duration_min: f.durMin ? Number(f.durMin) : null,
    duration_max: f.durMax ? Number(f.durMax) : null,
    sort: f.sort,
  };
}
function renderSearchFilters() {
  const tagsEl = $("filterTags");
  tagsEl.innerHTML = (S.library.tags || []).map(tag =>
    `<button class="filter-chip ${S.filters.tags.includes(tag) ? "active" : ""}" data-tag="${esc(tag)}">${esc(tag)}</button>`
  ).join("") || `<span class="muted" style="font-size:12px">${esc(t("nav_no_tags"))}</span>`;
  tagsEl.querySelectorAll("button[data-tag]").forEach(b => b.onclick = () => {
    const tag = b.dataset.tag;
    const i = S.filters.tags.indexOf(tag);
    if (i === -1) S.filters.tags.push(tag); else S.filters.tags.splice(i, 1);
    renderSearchFilters(); doSearch();
  });
  const folderEl = $("filterFolder");
  folderEl.innerHTML = `<option value="">${esc(t("option_any_folder"))}</option>` +
    (S.library.folders || []).map(f => `<option value="${esc(f)}">${esc(f)}</option>`).join("");
  folderEl.value = S.filters.folder;
  $("filterFav").checked = S.filters.favourite;
  $("filterDateFrom").value = S.filters.dateFrom;
  $("filterDateTo").value = S.filters.dateTo;
  $("filterDurMin").value = S.filters.durMin;
  $("filterDurMax").value = S.filters.durMax;
  $("filterSort").value = S.filters.sort;
}
function resetFilters() {
  S.filters = { tags: [], folder: "", favourite: false, dateFrom: "", dateTo: "", durMin: "", durMax: "", sort: "newest" };
  renderSearchFilters();
}

let _searchT = null;
function doSearch() {
  clearTimeout(_searchT);
  _searchT = setTimeout(() => {
    const q = $("searchInput").value.trim();
    if (!q && !filtersActive()) { renderList(); return; }
    api().search(q, filterPayload()).then(items => renderCards(items));
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
  initSidebarToggle();
  initListToggle();
  $("startBtn").onclick = startRecording;
  $("stopBtn").onclick = stopRecording;
  $("consentCheckbox").onchange = e => { $("consentContinue").disabled = !e.target.checked; };
  $("consentContinue").onclick = () => {
    api().acknowledge_consent().then(() => {
      S.consentAcknowledged = true;
      $("consentModal").classList.add("hidden");
    });
  };
  $("onboardContinue").onclick = () => {
    api().acknowledge_onboarding().then(() => {
      $("onboardModal").classList.add("hidden");
      maybeShowConsent();
    });
  };
  $("releaseNotesContinue").onclick = () => {
    api().acknowledge_release_notes().then(() => {
      $("releaseNotesModal").classList.add("hidden");
    });
  };
  $("recTitle").addEventListener("input", () => api().set_pending_title($("recTitle").value));

  $("searchToggle").onclick = () => {
    const sb = $("searchBar"); sb.classList.toggle("hidden");
    if (!sb.classList.contains("hidden")) { renderSearchFilters(); $("searchInput").focus(); }
  };
  $("searchClose").onclick = () => {
    $("searchBar").classList.add("hidden"); $("searchInput").value = ""; resetFilters(); renderList();
  };
  $("searchInput").addEventListener("input", doSearch);
  $("filterFolder").addEventListener("change", e => { S.filters.folder = e.target.value; doSearch(); });
  $("filterFav").addEventListener("change", e => { S.filters.favourite = e.target.checked; doSearch(); });
  $("filterDateFrom").addEventListener("change", e => { S.filters.dateFrom = e.target.value; doSearch(); });
  $("filterDateTo").addEventListener("change", e => { S.filters.dateTo = e.target.value; doSearch(); });
  $("filterDurMin").addEventListener("input", e => { S.filters.durMin = e.target.value; doSearch(); });
  $("filterDurMax").addEventListener("input", e => { S.filters.durMax = e.target.value; doSearch(); });
  $("filterSort").addEventListener("change", e => { S.filters.sort = e.target.value; doSearch(); });
  $("filterClear").onclick = () => { resetFilters(); doSearch(); };

  $("audioSettingsBtn").onclick = () => { $("audioModal").classList.remove("hidden"); loadDevices(); };
  $("audioClose").onclick = () => $("audioModal").classList.add("hidden");
  $("refreshDevices").onclick = () => api().get_devices().then(setDevices);
  $("outSelect").onchange = e => { S.selOut = parseInt(e.target.value, 10); setDevicePillsFromSel(); };
  $("inSelect").onchange = e => { S.selIn = parseInt(e.target.value, 10); setDevicePillsFromSel(); };

  $("appSettingsBtn").onclick = () => { $("appSettingsModal").classList.remove("hidden"); loadAppSettings(); };
  $("appSettingsClose").onclick = () => $("appSettingsModal").classList.add("hidden");
  $("profanityToggle").onchange = e => {
    api().set_profanity_filter(e.target.checked)
      .then(() => toast(e.target.checked ? t("toast_profanity_on") : t("toast_profanity_off")));
  };
  $("settingsLanguage").onchange = e => setLanguage(e.target.value);
  $("githubBtn").onclick = () => api().get_paths().then(p => api().open_url(p.source_url));

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
    const tr = (S.library.transcripts || []).find(x => x.id === id) || { id };
    if (actBtn) {
      e.stopPropagation();
      const a = actBtn.dataset.act;
      if (a === "copy") api().get_transcript(id).then(r => { copyText(r.body || ""); flashButton(actBtn, "✓"); toast(t("toast_copied")); });
      else if (a === "fav") api().toggle_favourite(id).then(refresh);
      else if (a === "move") openFolderPop(tr, actBtn);
      else if (a === "del") removeItem(tr);
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

  document.addEventListener("keydown", e => {
    if (e.key !== "Escape") return;
    closePop();
    if (S.detailFullscreen) setDetailFullscreen(false);
    else if (S.selectedId) closeDetail();
  });
  document.addEventListener("click", e => {
    if (!e.target.closest("#folderPop") && !e.target.closest('[data-act="move"]')) closePop();
  });
}
/* ---------- sidebar collapse (Loop-style icon rail) ---------- */
function initSidebarToggle() {
  const toggle = $("sidebarToggle"); if (!toggle) return;
  const sidebar = document.querySelector(".sidebar");
  const setCollapsed = (collapsed) => {
    sidebar.classList.toggle("collapsed", collapsed);
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.title = collapsed ? t("title_expand_sidebar") : t("title_collapse_sidebar");
    try { localStorage.setItem("ds_sidebar_collapsed", collapsed ? "1" : "0"); } catch (e) {}
  };
  let startCollapsed = false;
  try { startCollapsed = localStorage.getItem("ds_sidebar_collapsed") === "1"; } catch (e) {}
  setCollapsed(startCollapsed);
  toggle.onclick = () => setCollapsed(!sidebar.classList.contains("collapsed"));
}
function initListToggle() {
  const toggle = $("listToggle"); if (!toggle) return;
  const body = document.querySelector(".body");
  const setCollapsed = (collapsed) => {
    body.classList.toggle("list-collapsed", collapsed);
    toggle.title = collapsed ? t("title_expand_list") : t("title_collapse_list");
    try { localStorage.setItem("ds_list_collapsed", collapsed ? "1" : "0"); } catch (e) {}
  };
  let startCollapsed = false;
  try { startCollapsed = localStorage.getItem("ds_list_collapsed") === "1"; } catch (e) {}
  setCollapsed(startCollapsed);
  toggle.onclick = () => setCollapsed(!body.classList.contains("list-collapsed"));
}
function setDevicePillsFromSel() {
  const d = S.devices; if (!d) return;
  const outName = S.selOut < 0 ? t("pill_auto_outputs") : (d.outputs[S.selOut] ? d.outputs[S.selOut].name : "—");
  const inName = S.selIn < 0 ? t("pill_auto_mics") : (d.inputs[S.selIn] ? d.inputs[S.selIn].name : "—");
  $("devicePills").innerHTML =
    `<div class="pill" title="${esc(outName)}">🔊 ${esc(outName)}</div>` +
    `<div class="pill" title="${esc(inName)}">🎙 ${esc(inName)}</div>`;
}
