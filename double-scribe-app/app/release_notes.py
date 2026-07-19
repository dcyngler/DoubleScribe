"""Short per-version bullet points shown in the in-app "What's new" modal.

Kept terser than CHANGELOG.md (which is the full human-readable log) --
add an entry here at the same time you add one there. English-only; the UI
falls back to English for languages without a translation for these keys.
"""

NOTES = {
    "1.0.0": [
        "First public release of Double Scribe.",
        "Fully local, offline transcription -- audio never leaves your machine.",
        "Live \"Me\" / \"Them\" speaker bubbles as the call happens.",
        "Search, tag, and organize transcripts into folders.",
    ],
}
