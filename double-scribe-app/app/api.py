"""
pywebview bridge: exposes Python methods to the JS frontend, and pushes live
events back into the page. Owns a Store (metadata) and a LiveEngine (capture).
"""

import json
import threading
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import webview

from engine import LiveEngine
from store import Store, TRANSCRIPT_DIR
from settings import Settings
from release_notes import NOTES as RELEASE_NOTES

APP_VERSION = "1.0.0"
UPDATE_REPO = "dcyngler/DoubleScribe"   # GitHub repo checked for newer releases
SOURCE_URL = f"https://github.com/{UPDATE_REPO}"


def _version_tuple(v):
    """'1.2.0' -> (1, 2, 0); non-numeric parts (e.g. 'v1.2.0-beta') become 0."""
    parts = []
    for p in v.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


class Api:
    def __init__(self):
        self.store = Store()
        self.settings = Settings()
        self.engine = LiveEngine(
            on_phrase=self._on_phrase,
            on_status=self._on_status,
            on_saved=self._on_saved,
        )
        self.engine.censor_profanity = self.settings.get("profanity_filter")
        self._window = None
        self._ready = False
        self._status = "Starting up..."
        self._pending_title = ""

    # -- wiring -------------------------------------------------------------
    def attach(self, window):
        self._window = window

    def boot(self):
        """Runs on a background thread once the GUI is up."""
        threading.Thread(target=self._check_for_update, daemon=True).start()
        try:
            self.store.auto_import()
        except Exception:
            pass
        self._emit("onLibrary", self.store.list())
        try:
            self.engine.load()      # Whisper only -- fast
        except Exception as exc:
            self._on_status(f"Model load failed: {exc}")
            return
        self._ready = True
        self._on_status("ready")
        self._emit("onReady", self.engine.list_devices())   # recording usable now
        self.engine.load_speaker_model()   # slower ONNX cold-start; voice-split still optional
        self._emit("onReady", self.engine.list_devices())  # refresh has_voice_split once loaded

    # -- event push (Python -> JS) -----------------------------------------
    def _emit(self, fn, *args):
        if not self._window:
            return
        payload = ",".join(json.dumps(a, ensure_ascii=False) for a in args)
        try:
            self._window.evaluate_js(f"window.{fn} && window.{fn}({payload})")
        except Exception:
            pass

    def _on_phrase(self, label, text, voice_change=False):
        self._emit("onPhrase", label, text, voice_change)

    def _on_status(self, msg):
        self._status = msg
        self._emit("onStatus", msg)

    def _on_saved(self, meta):
        entry = self.store.add_recording(meta, self._pending_title)
        self._pending_title = ""
        self._emit("onSaved", entry)

    def _check_for_update(self):
        """Best-effort GitHub Releases check; silent no-op when offline or no releases exist yet."""
        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
                headers={"User-Agent": "DoubleScribe", "Accept": "application/vnd.github+json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            latest = (data.get("tag_name") or "").lstrip("vV")
            if latest and _version_tuple(latest) > _version_tuple(APP_VERSION):
                self._emit("onUpdateAvailable", {"version": latest, "url": data.get("html_url", "")})
        except Exception:
            pass

    # -- queries (JS -> Python) --------------------------------------------
    def get_status(self):
        return {"ready": self._ready, "message": self._status}

    def get_version(self):
        return APP_VERSION

    def open_url(self, url):
        try:
            webbrowser.open(url)
        except Exception:
            pass
        return True

    def get_settings(self):
        return self.settings.as_dict()

    def set_profanity_filter(self, enabled):
        enabled = bool(enabled)
        self.settings.set("profanity_filter", enabled)
        self.engine.censor_profanity = enabled
        return True

    def set_language(self, code):
        self.settings.set("language", code or "en")
        return True

    def acknowledge_consent(self):
        """User clicked through the recording-consent gate; record it (with a timestamp,
        so there's a trail showing the warning was shown and accepted, not just skipped)."""
        self.settings.set("consent_acknowledged", True)
        self.settings.set("consent_acknowledged_at", datetime.now(timezone.utc).isoformat())
        return True

    def acknowledge_onboarding(self):
        self.settings.set("onboarded", True)
        return True

    def check_whats_new(self):
        """Local-only comparison (no network) against the last version this install
        saw. Returns {version, notes} once per upgrade, or None if there's nothing
        new to show (fresh install, no version change, or no notes authored for the
        current version). Does not persist last_seen_version itself -- the caller
        must call acknowledge_release_notes() once the user has seen it, so a crash
        before that shows it again next launch instead of silently skipping it."""
        last_seen = self.settings.get("last_seen_version")
        if last_seen is None:
            # Fresh install -- onboarding covers this, not "what's new".
            self.settings.set("last_seen_version", APP_VERSION)
            return None
        if last_seen == APP_VERSION:
            return None
        notes = RELEASE_NOTES.get(APP_VERSION)
        if not notes:
            self.settings.set("last_seen_version", APP_VERSION)
            return None
        return {"version": APP_VERSION, "notes": notes}

    def acknowledge_release_notes(self):
        self.settings.set("last_seen_version", APP_VERSION)
        return True

    def get_paths(self):
        return {"source_url": SOURCE_URL}

    def get_library(self):
        return self.store.list()

    def get_devices(self):
        return self.engine.list_devices()

    def get_transcript(self, tid):
        return self.store.get_transcript(tid)

    def search(self, query, filters=None):
        return self.store.search(query, filters)

    # -- recording ----------------------------------------------------------
    def start(self, out_index, in_index, title=""):
        self._pending_title = title or ""
        try:
            return {"ok": True, "devices": self.engine.start(int(out_index), int(in_index))}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def set_pending_title(self, title):
        self._pending_title = title or ""
        return True

    def stop(self, title=""):
        if title:
            self._pending_title = title
        self.engine.stop()
        return True

    # -- metadata mutations -------------------------------------------------
    def set_title(self, tid, title):
        return self.store.set_title(tid, title)

    def add_tag(self, tid, tag):
        return self.store.add_tag(tid, tag)

    def remove_tag(self, tid, tag):
        return self.store.remove_tag(tid, tag)

    def create_folder(self, name):
        return self.store.create_folder(name)

    def set_folder(self, tid, folder):
        return self.store.set_folder(tid, folder)

    def toggle_favourite(self, tid):
        return self.store.toggle_favourite(tid)

    def remove_from_library(self, tid):
        """UI 'delete': hides the item but keeps the .txt on disk (policy)."""
        path = self.store.file_path(tid)
        self.store.archive(tid)
        return {"ok": True, "kept_at": path}

    # -- export -------------------------------------------------------------
    def export_txt(self, tid):
        t = self.store._by_id(tid)
        if not t:
            return {"ok": False}
        src = TRANSCRIPT_DIR / t["filename"]
        safe = "".join(c for c in t["title"] if c.isalnum() or c in " -_").strip() or "transcript"
        try:
            result = self._window.create_file_dialog(
                webview.SAVE_DIALOG, save_filename=f"{safe}.txt")
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        if not result:
            return {"ok": False, "cancelled": True}
        dest = result[0] if isinstance(result, (list, tuple)) else result
        try:
            Path(dest).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            return {"ok": True, "path": dest}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
