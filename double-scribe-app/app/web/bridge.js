"use strict";
/*
 * Shim so app.js's window.pywebview.api.* calls work over plain HTTP when
 * served by app/server.py (browser test mode), instead of the native
 * pywebview bridge. Only injected into index.html by server.py -- the
 * native app (app.py) never loads this file, so it can't affect it.
 */
(function () {
  if (window.pywebview) return;

  const METHODS = [
    "get_status", "get_library", "get_devices", "get_transcript", "search",
    "start", "set_pending_title", "stop", "set_title", "add_tag", "remove_tag",
    "create_folder", "set_folder", "toggle_favourite", "remove_from_library",
    "export_txt", "get_version", "open_url",
    "get_settings", "set_profanity_filter", "get_paths",
  ];

  function call(method, args) {
    return fetch("/api/" + method, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args || []),
    }).then(r => r.json());
  }

  const api = {};
  METHODS.forEach(name => { api[name] = (...args) => call(name, args); });

  // No native save dialog in a browser -- trigger a real file download instead.
  const rawExport = api.export_txt;
  api.export_txt = (tid) => rawExport(tid).then(r => {
    if (r && r.ok && r.download) {
      const a = document.createElement("a");
      a.href = r.download;
      document.body.appendChild(a);
      a.click();
      a.remove();
    }
    return r;
  });

  window.pywebview = { api };

  const es = new EventSource("/events");
  es.onmessage = (ev) => {
    try {
      const { fn, args } = JSON.parse(ev.data);
      if (typeof window[fn] === "function") window[fn](...args);
    } catch (e) { console.error("bridge: bad event", e); }
  };

  window.dispatchEvent(new Event("pywebviewready"));
})();
