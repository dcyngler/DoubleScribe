"""
Headless live-transcription controller for the new UI.

This does NOT reimplement the engine -- it reuses the working pieces from the
existing live_transcriber.py / transcriber.py (capture, endpointing, speaker
matching, Whisper loading, save formatting) and just drives them without a
Tkinter GUI, reporting results through plain callbacks so any frontend can
consume them.
"""

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
import live_transcriber as live       # LiveChannel, SpeakerTracker, transcribe_utterance, constants

SAMPLE_RATE = live.SAMPLE_RATE


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
        self.tracker = None
        self.recording = False

        self.channels = []
        self.stop_event = None
        self.work_q = None
        self._worker_thread = None
        self._session_tracker = None   # tracker snapshot for the current session
        self._recent = []              # recent phrases, for duplicate suppression
        self.session = []              # [(label, text), ...]

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
        """Load the speaker-ID model (slow ONNX cold-start) in the background."""
        try:
            if core.DIAR_EMB_MODEL.exists():
                self.tracker = live.SpeakerTracker(core.DIAR_EMB_MODEL)
        except Exception:
            self.tracker = None
        return self.tracker is not None

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
            "has_speaker_id": self.tracker is not None,
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

        self.session = []
        self._recent = []
        self.stop_event = threading.Event()
        self.work_q = queue.Queue()
        if self.tracker:
            self.tracker.reset()

        self.channels = [
            live.LiveChannel(lambda d=dev: d, label, self.work_q, self.stop_event, sil)
            for (label, dev, sil) in specs
        ]
        for c in self.channels:
            c.start()

        self._session_tracker = self.tracker   # snapshot so a session is consistent
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
            text = live.transcribe_utterance(self.model, audio)
            if not text:
                continue
            # suppress duplicates: the same phrase captured by two devices at once
            norm = " ".join(text.lower().split())
            now = time.monotonic()
            self._recent = [(l, n, t) for (l, n, t) in self._recent if now - t < 6]
            if any(l == label and n == norm for (l, n, t) in self._recent):
                continue
            self._recent.append((label, norm, now))
            # Labels stay as the physical source: "Me" (mic) or "Them" (speakers).
            self.session.append((label, text))
            self.on_phrase(label, text)

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
        threading.Thread(target=self._finish, daemon=True).start()

    def _finish(self):
        for c in self.channels:
            c.join(timeout=5)
        if self._worker_thread:
            self._worker_thread.join(timeout=60)
        meta = self._save()
        self.on_saved(meta)

    def _save(self):
        """Write live-YYYYMMDD-HHMMSS.txt exactly like the existing tool."""
        started = self._start_ts or datetime.datetime.now()
        now = datetime.datetime.now()
        preview_lines = [t for (_, t) in self.session][:2]
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
        turns = core.group_turns([(i, lbl, txt) for i, (lbl, txt) in enumerate(self.session)])
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
