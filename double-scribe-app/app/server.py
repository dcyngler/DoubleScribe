"""
Double Scribe -- local browser test server.

Standalone alternative to app.py: serves the same app/web frontend over plain
HTTP instead of a native pywebview window, so it can be opened in a regular
browser at http://127.0.0.1:8765. Not used by the packaged/native app --
app.py is still the real entrypoint; this exists for testing the UI in a
browser's devtools.

Bridges window.pywebview.api calls (see web/bridge.js) to the same Api class
the native app uses: JS -> POST /api/<method>, Python -> JS push events over
a Server-Sent Events stream at /events. export_txt has no native save dialog
here, so it triggers a browser download instead (see WebApi.export_txt).
"""

import json
import queue
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import Api
from store import TRANSCRIPT_DIR

HERE = Path(__file__).resolve().parent
WEB_DIR = HERE / "web"
HOST, PORT = "127.0.0.1", 8765

ALLOWED_METHODS = {
    "get_status", "get_library", "get_devices", "get_transcript", "search",
    "start", "set_pending_title", "stop", "set_title", "add_tag", "remove_tag",
    "create_folder", "set_folder", "toggle_favourite", "remove_from_library",
    "export_txt",
}

BRIDGE_TAG = '<script src="bridge.js"></script>\n<script src="app.js"></script>'

CONTENT_TYPES = {
    ".js": "application/javascript",
    ".css": "text/css",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".html": "text/html",
}


class WebApi(Api):
    """Api with the native-only bits (evaluate_js, save dialog) swapped for
    HTTP equivalents (SSE push, download link)."""

    def __init__(self):
        super().__init__()
        self._subs = []
        self._subs_lock = threading.Lock()

    def _emit(self, fn, *args):
        msg = json.dumps({"fn": fn, "args": args}, ensure_ascii=False)
        with self._subs_lock:
            subs = list(self._subs)
        for q in subs:
            q.put(msg)

    def export_txt(self, tid):
        t = self.store._by_id(tid)
        if not t:
            return {"ok": False}
        return {"ok": True, "download": f"/download/{tid}"}

    def subscribe(self):
        q = queue.Queue()
        with self._subs_lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q):
        with self._subs_lock:
            if q in self._subs:
                self._subs.remove(q)


api = WebApi()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/events":
            self._handle_events()
        elif self.path.startswith("/download/"):
            self._handle_download(self.path[len("/download/"):])
        else:
            self._serve_static()

    def do_POST(self):
        if self.path.startswith("/api/"):
            self._handle_api(self.path[len("/api/"):])
        else:
            self.send_error(404)

    def _handle_api(self, method):
        if method not in ALLOWED_METHODS:
            self._send_json({"error": "unknown method"}, 404)
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"[]"
        try:
            args = json.loads(raw) if raw else []
        except Exception:
            args = []
        try:
            result = getattr(api, method)(*args)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)
            return
        self._send_json(result)

    def _handle_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = api.subscribe()
        try:
            while True:
                msg = q.get()
                self.wfile.write(f"data: {msg}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass
        finally:
            api.unsubscribe(q)

    def _handle_download(self, tid):
        t = api.store._by_id(tid)
        if not t:
            self.send_error(404)
            return
        path = TRANSCRIPT_DIR / t["filename"]
        try:
            data = path.read_text(encoding="utf-8").encode("utf-8")
        except Exception:
            self.send_error(404)
            return
        safe = "".join(c for c in t["title"] if c.isalnum() or c in " -_").strip() or "transcript"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{safe}.txt"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self):
        rel = self.path.split("?", 1)[0].lstrip("/") or "index.html"
        fpath = (WEB_DIR / rel).resolve()
        if fpath != WEB_DIR and WEB_DIR not in fpath.parents:
            self.send_error(403)
            return
        if not fpath.is_file():
            self.send_error(404)
            return
        if fpath.name == "index.html":
            html = fpath.read_text(encoding="utf-8").replace(
                '<script src="app.js"></script>', BRIDGE_TAG)
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        data = fpath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(fpath.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    print(f"Double Scribe (browser test mode) -- http://{HOST}:{PORT}")
    print("Loading Whisper model in the background; the page works before it finishes.")
    threading.Thread(target=api.boot, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
