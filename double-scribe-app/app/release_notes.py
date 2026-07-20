"""Short per-version bullet points shown in the in-app "What's new" modal.

Kept terser than CHANGELOG.md (which is the full human-readable log) --
add an entry here at the same time you add one there. English-only; the UI
falls back to English for languages without a translation for these keys.
"""

NOTES = {
    "0.4.3": [
        "The recording-consent notice will show once more, even if you've already seen it.",
    ],
    "0.4.2": [
        "Donate button is now live.",
        "Security hardening for the auto-updater.",
    ],
    "0.4.1": [
        "First public release of Double Scribe.",
        "Fully local, offline transcription -- audio never leaves your machine.",
        "Live \"Me\" / \"Them\" speaker bubbles as the call happens.",
        "Search, tag, and organize transcripts into folders.",
        "Added a Theme setting: System, Light, or Dark.",
        "Live view now shows a waiting indicator between turns.",
        "Click outside a dialog to close it.",
    ],
}
