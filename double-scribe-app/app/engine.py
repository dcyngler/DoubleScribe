"""
Headless live-transcription controller for the new UI.

This does NOT reimplement the engine -- it reuses the working pieces from the
existing live_transcriber.py / transcriber.py (capture, endpointing, speaker
matching, Whisper loading, save formatting) and just drives them without a
Tkinter GUI, reporting results through plain callbacks so any frontend can
consume them.
"""

import os
import sys
import time
import queue
import threading
import datetime
from pathlib import Path

# Make the sibling engine modules (one folder up) importable.
_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

import transcriber as core            # load_model, group_turns, TRANSCRIPT_DIR, DIAR_EMB_MODEL
import live_transcriber as live       # LiveChannel, VoiceChangeDetector, transcribe_utterance, constants
import profanity_filter

SAMPLE_RATE = live.SAMPLE_RATE

# A couple of our UI language codes don't match Whisper's own codes 1:1 --
# Whisper doesn't distinguish Simplified/Traditional Chinese script.
_WHISPER_LANG_OVERRIDES = {"zh-Hans": "zh", "zh-Hant": "zh"}


def _whisper_language(code):
    """Map a settings transcription_language value to faster-whisper's
    `language=` argument: None for auto-detect, else a Whisper language code."""
    if not code or code == "auto":
        return None
    return _WHISPER_LANG_OVERRIDES.get(code, code)

# Temporary diagnostics for the live-latency/stop-hang investigation (see
# claude/plans -- "Investigate & fix live-transcription latency/stop-hang
# regression"). Off by default; set DS_LIVE_DEBUG=1 to print channel counts,
# work-queue backlog, per-utterance real-time factor, and stop-drain timing
# to stderr. Safe to leave in (no-op unless the env var is set) or strip once
# the investigation concludes.
_DEBUG = os.environ.get("DS_LIVE_DEBUG") == "1"


def _dbg(msg):
    if _DEBUG:
        print(f"[live-debug {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def _group_turns(session):
    """Like transcriber.group_turns, but a 'Them' phrase flagged as a voice
    change starts a new turn even though the label ('Them') didn't change --
    so a different remote voice shows as a separate bubble, unnamed."""
    turns = []
    for label, text, voice_change in session:
        if turns and turns[-1][0] == label and not (label == "Them" and voice_change):
            turns[-1][1].append(text)
        else:
            turns.append([label, [text]])
    return [(label, core.format_dictated_lists(" ".join(p.strip() for p in parts).strip()))
            for label, parts in turns]


class LiveEngine:
    """Reuses the existing live pipeline; reports phrases via callbacks."""

    def __init__(self, on_phrase=None, on_status=None, on_saved=None):
        self.on_phrase = on_phrase or (lambda label, text: None)
        self.on_status = on_status or (lambda msg: None)
        self.on_saved = on_saved or (lambda meta: None)

        self.model = None
        self.voice_detector = None
        self.recording = False
        self.censor_profanity = False
        self.transcription_language = "auto"

        self.channels = []
        self.stop_event = None
        self.work_q = None
        self._worker_thread = None
        self._session_detector = None  # voice detector snapshot for the current session
        self._recent = []              # recent phrases, for duplicate suppression
        self.session = []              # [(label, text, voice_change), ...]

        self._start_ts = None
        self._elapsed = 0

        self._speakers = []
        self._mics = []

    # -- model load ---------------------------------------------------------
    def load(self):
        """Load Whisper only -- fast, so recording is usable quickly."""
        self.model = core.load_model(self.on_status)
        return self.model is not None

    def load_speaker_model(self):
        """Load the voice-change model (slow ONNX cold-start) in the background.
        No naming/identity -- just enough to tell 'Them' phrases apart so a
        different remote voice gets its own bubble."""
        try:
            if core.DIAR_EMB_MODEL.exists():
                self.voice_detector = live.VoiceChangeDetector(core.DIAR_EMB_MODEL)
        except Exception:
            self.voice_detector = None
        return self.voice_detector is not None

    # -- devices ------------------------------------------------------------
    def list_devices(self):
        import soundcard as sc
        self._speakers = sc.all_speakers()
        self._mics = sc.all_microphones()
        try:
            def_spk = sc.default_speaker().name
        except Exception:
            def_spk = None
        try:
            def_mic = sc.default_microphone().name
        except Exception:
            def_mic = None
        out_default = next((i for i, s in enumerate(self._speakers) if s.name == def_spk), 0)
        in_default = next((i for i, m in enumerate(self._mics) if m.name == def_mic), 0)
        return {
            "outputs": [{"name": s.name} for s in self._speakers],
            "inputs": [{"name": m.name} for m in self._mics],
            "output_default": out_default,
            "input_default": in_default,
            "has_voice_split": self.voice_detector is not None,
        }

    # -- start / stop -------------------------------------------------------
    def start(self, out_index=-1, in_index=-1):
        """Start capture. index < 0 (default) = AUTO: capture *every* output and
        *every* microphone at once; silent devices contribute nothing, the active
        one transcribes -- so there is nothing to choose. A specific index pins a
        single device instead."""
        if self.recording:
            return None
        import soundcard as sc
        self.list_devices()
        out_index = int(out_index) if out_index is not None else -1
        in_index = int(in_index) if in_index is not None else -1

        them_sil = max(1, round(live.END_SILENCE_THEM / live.CHUNK_SECONDS))
        me_sil = max(1, round(live.END_SILENCE_ME / live.CHUNK_SECONDS))

        # choose device sets (all, or one pinned)
        if out_index < 0:
            out_devs = self._speakers or [sc.default_speaker()]
        else:
            out_devs = [self._speakers[out_index]] if 0 <= out_index < len(self._speakers) else [sc.default_speaker()]
        if in_index < 0:
            in_devs = self._mics or [sc.default_microphone()]
        else:
            in_devs = [self._mics[in_index]] if 0 <= in_index < len(self._mics) else [sc.default_microphone()]

        specs = []   # (label, device, end_silence_chunks)
        for spk in out_devs:
            try:
                specs.append(("Them", sc.get_microphone(id=str(spk.name), include_loopback=True), them_sil))
            except Exception:
                pass   # skip endpoints that can't open
        for mic in in_devs:
            specs.append(("Me", mic, me_sil))
        if not specs:
            raise RuntimeError("No audio devices available to capture")

        _dbg(f"start(out_index={out_index}, in_index={in_index}): opening {len(specs)} "
             f"channel(s) -- Them={[d.name for (l, d, s) in specs if l == 'Them']}, "
             f"Me={[d.name for (l, d, s) in specs if l == 'Me']}")

        self.session = []
        self._recent = []
        self.stop_event = threading.Event()
        self.work_q = queue.Queue()
        if self.voice_detector:
            self.voice_detector.reset()

        self.channels = [
            live.LiveChannel(lambda d=dev: d, label, self.work_q, self.stop_event, sil)
            for (label, dev, sil) in specs
        ]
        for c in self.channels:
            c.start()

        self._session_detector = self.voice_detector   # snapshot so a session is consistent
        self.recording = True
        self._start_ts = datetime.datetime.now()
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()
        return {
            "auto": out_index < 0 and in_index < 0,
            "outputs": sum(1 for s in specs if s[0] == "Them"),
            "mics": sum(1 for s in specs if s[0] == "Me"),
        }

    def _worker(self):
        while not (self.stop_event.is_set() and self.work_q.empty()):
            try:
                label, audio = self.work_q.get(timeout=0.2)
            except queue.Empty:
                continue
            if _DEBUG:
                dur = audio.size / SAMPLE_RATE
                t0 = time.monotonic()
            text = live.transcribe_utterance(
                self.model, audio, language=_whisper_language(self.transcription_language))
            backlog = self.work_q.qsize()   # still-pending chunks -- growth = falling behind
            if _DEBUG:
                infer = time.monotonic() - t0
                rtf = infer / dur if dur else float("inf")
                _dbg(f"[{label}] audio={dur:.2f}s infer={infer:.2f}s RTF={rtf:.2f} "
                     f"backlog_remaining={backlog}")
            if self.stop_event.is_set():
                # Stop was pressed but there's still a queued backlog to transcribe before
                # _finish() can save -- surface it instead of a silent "Saving..." hang.
                self.on_status(
                    f"Finishing -- transcribing {backlog} more phrase(s)..." if backlog
                    else "Finishing -- saving...")
            if not text:
                continue
            if self.censor_profanity:
                text = profanity_filter.censor(text)
            # suppress duplicates: the same phrase captured by two devices at once
            norm = " ".join(text.lower().split())
            now = time.monotonic()
            self._recent = [(l, n, t) for (l, n, t) in self._recent if now - t < 6]
            if any(l == label and n == norm for (l, n, t) in self._recent):
                continue
            self._recent.append((label, norm, now))
            # Labels stay as the physical source: "Me" (mic) or "Them" (speakers).
            # A "Them" phrase that sounds like a different voice than the last
            # one gets flagged, so the UI can start a new bubble -- no naming.
            voice_change = False
            if label == "Them" and self._session_detector:
                try:
                    voice_change = self._session_detector.changed(audio)
                except Exception:
                    voice_change = False
            self.session.append((label, text, voice_change))
            self.on_phrase(label, text, voice_change)

    def elapsed_seconds(self):
        if not self._start_ts:
            return self._elapsed
        return int((datetime.datetime.now() - self._start_ts).total_seconds())

    def stop(self):
        """Non-blocking: signal stop, then finish + save on a background thread."""
        if not self.recording:
            return
        self.recording = False
        self._elapsed = self.elapsed_seconds()
        self.stop_event.set()
        _dbg(f"stop(): work_q backlog at stop-signal={self.work_q.qsize()}")
        threading.Thread(target=self._finish, daemon=True).start()

    def _finish(self):
        t0 = time.monotonic()
        for c in self.channels:
            tj = time.monotonic()
            c.join(timeout=5)
            _dbg(f"_finish(): joined channel '{c.label}' in {time.monotonic() - tj:.2f}s "
                 f"(alive={c.is_alive()})")
        if self._worker_thread:
            backlog = self.work_q.qsize()
            tw = time.monotonic()
            self._worker_thread.join(timeout=60)
            _dbg(f"_finish(): worker drained {backlog} pending chunk(s) in "
                 f"{time.monotonic() - tw:.2f}s (alive={self._worker_thread.is_alive()})")
        _dbg(f"_finish(): total stop-to-save time {time.monotonic() - t0:.2f}s")
        meta = self._save()
        self.on_saved(meta)

    def _save(self):
        """Write live-YYYYMMDD-HHMMSS.txt exactly like the existing tool."""
        started = self._start_ts or datetime.datetime.now()
        now = datetime.datetime.now()
        preview_lines = [t for (_, t, _) in self.session][:2]
        meta = {
            "filename": None,
            "duration_seconds": self._elapsed,
            "created": started.isoformat(timespec="seconds"),
            "preview": " ".join(preview_lines)[:200],
            "first_line": (self.session[0][1] if self.session else ""),
        }
        if not self.session:
            return meta

        core.TRANSCRIPT_DIR.mkdir(exist_ok=True)
        fname = core.TRANSCRIPT_DIR / f"live-{now:%Y%m%d-%H%M%S}.txt"
        turns = _group_turns(self.session)
        with open(fname, "w", encoding="utf-8") as fh:
            fh.write(f"Live transcript -- {now:%Y-%m-%d %H:%M:%S}\n")
            fh.write("=" * 40 + "\n\n")
            for label, text in turns:
                lines = text.split("\n")
                if len(lines) == 1:
                    fh.write(f"{label}: {lines[0]}\n")
                else:
                    fh.write(f"{label}:\n")
                    for ln in lines:
                        fh.write(f"    {ln}\n")
        meta["filename"] = fname.name
        return meta
