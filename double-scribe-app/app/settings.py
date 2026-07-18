"""Persisted app-level preferences (settings.json in the writable data dir)."""

import sys
import json
from pathlib import Path

_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

import transcriber as core   # for DATA_DIR (packaging-aware)

SETTINGS_PATH = core.DATA_DIR / "settings.json"

_DEFAULTS = {
    "profanity_filter": False,
    "consent_acknowledged": False,
    "consent_acknowledged_at": None,
}


class Settings:
    def __init__(self):
        self._data = dict(_DEFAULTS)
        self._load()

    def _load(self):
        try:
            saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            self._data.update({k: v for k, v in saved.items() if k in _DEFAULTS})
        except Exception:
            pass

    def _save(self):
        try:
            SETTINGS_PATH.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def as_dict(self):
        return dict(self._data)

    def get(self, key):
        return self._data.get(key, _DEFAULTS.get(key))

    def set(self, key, value):
        if key not in _DEFAULTS:
            return
        self._data[key] = value
        self._save()
