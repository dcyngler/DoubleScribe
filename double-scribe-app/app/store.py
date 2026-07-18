"""
index.json manager for the new UI.

Owns metadata only (titles, tags, folders, favourites, previews). The transcript
.txt files themselves are never modified or deleted here -- "delete" is an
archive flag that hides an item from the library while keeping the file on disk
(the organisation's policy forbids deleting files).
"""

import re
import sys
import json
import uuid
import datetime
from pathlib import Path

_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

import transcriber as core   # for TRANSCRIPT_DIR / INDEX_PATH (packaging-aware)

INDEX_PATH = core.INDEX_PATH
TRANSCRIPT_DIR = core.TRANSCRIPT_DIR
_NAME_RE = re.compile(r"(?:live|transcript)-(\d{8})-(\d{6})", re.I)
_SPK_RE = re.compile(r"\bSpeaker\s+\d+\b")


def _collapse_speakers(text):
    """Show older transcripts as Me/Them only -- display-only, files unchanged."""
    return _SPK_RE.sub("Them", text or "")


_MSG_RE = re.compile(r"^(Me|Them|Speaker \d+):\s?(.*)$")


def parse_messages(body):
    """Turn a transcript body into chat messages [{'who','text'}].
    'Me' -> me (right/blue); Them or any Speaker N -> them (left/grey).
    A bare 'Label:' followed by indented lines (dictated lists) is one message."""
    msgs = []
    cur = None
    for line in (body or "").split("\n"):
        m = _MSG_RE.match(line)
        if m:
            who = "me" if m.group(1) == "Me" else "them"
            cur = {"who": who, "lines": ([m.group(2)] if m.group(2) else [])}
            msgs.append(cur)
        elif cur is not None:
            cur["lines"].append(line.strip())
    out = []
    for c in msgs:
        text = "\n".join(c["lines"]).strip()
        if text:
            out.append({"who": c["who"], "text": text})
    return out


def _parse_created(filename):
    m = _NAME_RE.search(filename)
    if not m:
        return None
    try:
        dt = datetime.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        return dt.isoformat(timespec="seconds")
    except ValueError:
        return None


def _strip_header(text):
    """Drop the 'Live transcript -- ... / ====' header, return the body."""
    lines = text.splitlines()
    i = 0
    if lines and (lines[0].startswith("Live transcript") or lines[0].startswith("Transcript")):
        i = 1
        if i < len(lines) and set(lines[i].strip()) <= {"="}:
            i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
    return "\n".join(lines[i:])


def _derive_title(body):
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        s = re.sub(r"^(Me|Them|Speaker \d+)\s*:\s*", "", s)  # drop speaker label
        s = s.strip()
        if s:
            return s[:60]
    return "Untitled transcript"


class Store:
    def __init__(self):
        self.data = self._load()
        self._content_cache = {}

    # -- persistence --------------------------------------------------------
    def _default(self):
        return {"transcripts": [], "folders": [], "tags": []}

    def _load(self):
        if INDEX_PATH.exists():
            try:
                data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
                for k, v in self._default().items():
                    data.setdefault(k, v)
                return data
            except Exception:
                pass
        return self._default()

    def save(self):
        INDEX_PATH.write_text(json.dumps(self.data, indent=2, ensure_ascii=False),
                              encoding="utf-8")

    # -- helpers ------------------------------------------------------------
    def _by_id(self, tid):
        return next((t for t in self.data["transcripts"] if t["id"] == tid), None)

    def _file_body(self, filename):
        if filename in self._content_cache:
            return self._content_cache[filename]
        path = TRANSCRIPT_DIR / filename
        try:
            body = _strip_header(path.read_text(encoding="utf-8"))
        except Exception:
            body = ""
        self._content_cache[filename] = body
        return body

    # -- import -------------------------------------------------------------
    def auto_import(self):
        known = {t["filename"] for t in self.data["transcripts"]}
        added = 0
        if TRANSCRIPT_DIR.exists():
            for path in sorted(TRANSCRIPT_DIR.glob("*.txt")):
                if path.name in known:
                    continue
                body = self._file_body(path.name)
                self.data["transcripts"].append({
                    "id": str(uuid.uuid4()),
                    "filename": path.name,
                    "title": _derive_title(body),
                    "created": _parse_created(path.name) or datetime.datetime.fromtimestamp(
                        path.stat().st_mtime).isoformat(timespec="seconds"),
                    "duration_seconds": None,
                    "tags": [],
                    "folder": None,
                    "favourite": False,
                    "archived": False,
                    "preview": " ".join(body.split())[:200],
                })
                added += 1
        if added:
            self.save()
        return added

    # -- reads --------------------------------------------------------------
    def _view(self, t):
        """A display copy with Speaker N collapsed to Them (files untouched)."""
        v = dict(t)
        v["preview"] = _collapse_speakers(v.get("preview", ""))
        v["title"] = _collapse_speakers(v.get("title", ""))
        return v

    def list(self):
        items = [t for t in self.data["transcripts"] if not t.get("archived")]
        items.sort(key=lambda t: t.get("created") or "", reverse=True)
        return {
            "transcripts": [self._view(t) for t in items],
            "folders": self.data["folders"],
            "tags": self.data["tags"],
        }

    def get_transcript(self, tid):
        t = self._by_id(tid)
        if not t:
            return None
        body = _collapse_speakers(self._file_body(t["filename"]))
        return {"meta": self._view(t), "body": body, "messages": parse_messages(body)}

    def search(self, query, filters=None):
        q = (query or "").strip().lower()
        f = filters or {}
        tags = f.get("tags") or []
        folder = f.get("folder") or None
        favourite_only = bool(f.get("favourite"))
        date_from = f.get("date_from") or None
        date_to = f.get("date_to") or None
        dur_min = f.get("duration_min")
        dur_max = f.get("duration_max")
        sort = f.get("sort") or "newest"

        hits = []
        for t in self.data["transcripts"]:
            if t.get("archived"):
                continue
            if q:
                hay = " ".join([t.get("title", ""), " ".join(t.get("tags", [])),
                                self._file_body(t["filename"])]).lower()
                if q not in hay:
                    continue
            if tags and not any(tag in t.get("tags", []) for tag in tags):
                continue
            if folder and t.get("folder") != folder:
                continue
            if favourite_only and not t.get("favourite"):
                continue
            created = t.get("created") or ""
            if date_from and created[:10] < date_from:
                continue
            if date_to and created[:10] > date_to:
                continue
            dur = t.get("duration_seconds")
            if dur_min is not None and (dur is None or dur < dur_min * 60):
                continue
            if dur_max is not None and (dur is None or dur > dur_max * 60):
                continue
            hits.append(t)

        sort_keys = {
            "newest": (lambda t: t.get("created") or "", True),
            "oldest": (lambda t: t.get("created") or "", False),
            "longest": (lambda t: t.get("duration_seconds") or 0, True),
            "shortest": (lambda t: t.get("duration_seconds") or 0, False),
        }
        key, reverse = sort_keys.get(sort, sort_keys["newest"])
        hits.sort(key=key, reverse=reverse)
        return [self._view(t) for t in hits]

    # -- record a freshly finished session ---------------------------------
    def add_recording(self, meta, title=None):
        if not meta or not meta.get("filename"):
            return None
        body = self._file_body(meta["filename"])
        entry = {
            "id": str(uuid.uuid4()),
            "filename": meta["filename"],
            "title": (title or "").strip() or _derive_title(body),
            "created": meta.get("created") or datetime.datetime.now().isoformat(timespec="seconds"),
            "duration_seconds": meta.get("duration_seconds"),
            "tags": [],
            "folder": None,
            "favourite": False,
            "archived": False,
            "preview": meta.get("preview") or " ".join(body.split())[:200],
        }
        self.data["transcripts"].insert(0, entry)
        self.save()
        return entry

    # -- mutations (metadata only) -----------------------------------------
    def set_title(self, tid, title):
        t = self._by_id(tid)
        if t:
            t["title"] = (title or "").strip() or t["title"]
            self.save()
        return t

    def _register_tag(self, tag):
        if tag and tag not in self.data["tags"]:
            self.data["tags"].append(tag)

    def add_tag(self, tid, tag):
        tag = (tag or "").strip()
        t = self._by_id(tid)
        if t and tag and tag not in t["tags"]:
            t["tags"].append(tag)
            self._register_tag(tag)
            self.save()
        return t

    def remove_tag(self, tid, tag):
        t = self._by_id(tid)
        if t and tag in t.get("tags", []):
            t["tags"].remove(tag)
            self.save()
        return t

    def create_folder(self, name):
        name = (name or "").strip()
        if name and name not in self.data["folders"]:
            self.data["folders"].append(name)
            self.save()
        return self.data["folders"]

    def set_folder(self, tid, folder):
        t = self._by_id(tid)
        if t:
            t["folder"] = folder or None
            if folder:
                self.create_folder(folder)
            self.save()
        return t

    def toggle_favourite(self, tid):
        t = self._by_id(tid)
        if t:
            t["favourite"] = not t.get("favourite", False)
            self.save()
        return t

    def archive(self, tid):
        """'Delete' from the UI's point of view -- hides it but keeps the file."""
        t = self._by_id(tid)
        if t:
            t["archived"] = True
            self.save()
        return t

    def file_path(self, tid):
        t = self._by_id(tid)
        return str((TRANSCRIPT_DIR / t["filename"]).resolve()) if t else None
