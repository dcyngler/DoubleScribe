"""Word-boundary profanity censor for live transcripts.

Replaces matched words with the first letter followed by asterisks
(e.g. "shit" -> "s***"), so the transcript stays readable but the
word itself is masked. Applied only when the user turns the "Filter
profanity" toggle on in App settings.
"""

import re

_WORDS = [
    "fuck", "fucking", "fucker", "fucked", "motherfucker",
    "shit", "shitty", "bullshit",
    "bitch", "bitches",
    "asshole", "ass",
    "bastard",
    "damn", "goddamn",
    "crap",
    "piss", "pissed",
    "dick", "dickhead",
    "cock",
    "pussy",
    "cunt",
    "twat",
    "slut",
    "whore",
    "douche", "douchebag",
    "prick",
    "wanker",
    "bollocks",
    "arse", "arsehole",
]

_PATTERN = re.compile(r"\b(" + "|".join(re.escape(w) for w in _WORDS) + r")\b", re.IGNORECASE)


def _mask(match):
    word = match.group(0)
    return word[0] + "*" * (len(word) - 1)


def censor(text):
    """Mask profane words in text, preserving everything else as-is."""
    if not text:
        return text
    return _PATTERN.sub(_mask, text)
