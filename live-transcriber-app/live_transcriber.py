"""
Live audio transcriber.

Same idea as transcriber.py -- captures your microphone (Me) and your computer's
audio output (Them) -- but instead of transcribing everything at the end, it
transcribes *as you go*: it watches for natural pauses, and the moment someone
finishes a phrase it transcribes just that phrase and prints it straight away.

Remote speakers are separated live by matching each phrase's voiceprint against
the voices heard so far, so you get Speaker 1 / Speaker 2 / ... in real time.
(Live matching is approximate -- it cannot re-analyse the whole call the way the
end-of-call tool can -- but with clean, one-speaker-at-a-time phrases it works
well.)

This file does NOT modify transcriber.py; it reuses its model loading and text
helpers by importing it.

Everything runs offline. Nothing is uploaded; audio is never written to disk.
"""

import queue
import threading
import datetime
import traceback
from collections import deque
from pathlib import Path

import numpy as np
import soundcard as sc
import tkinter as tk

# Reuse the sibling tool's setup (CUDA dll dirs, model loader, text helpers).
# Importing it runs no GUI -- it only defines things.
import transcriber as core

SAMPLE_RATE = core.SAMPLE_RATE          # 16 kHz

# ---------------------------------------------------------------------------
# Live tuning -- how the endpointer decides a phrase is finished
# ---------------------------------------------------------------------------
CHUNK_SECONDS = 0.1                     # audio pulled per step (100 ms)
# End-of-phrase silence, per channel. Generous for you (one voice, keep sentences
# whole); tight for the remote side (so separate speakers don't get glued together).
END_SILENCE_ME = 1.0                    # raise if your own sentences still get cut
END_SILENCE_THEM = 0.5                  # lower if remote speakers get merged
MIN_SPEECH = 0.25                       # ignore blips shorter than this
MAX_UTTERANCE = 12.0                    # force a flush if a phrase runs this long
PREROLL = 0.4                           # audio kept before speech so onsets aren't clipped
MIN_RMS = 0.004                         # absolute speech energy floor (lower = more sensitive)
SPEECH_MULT = 2.0                       # ... or this much above the noise floor (lower = more sensitive)

# Live speaker matching (Them channel)
SPEAKER_MATCH_THRESHOLD = 0.5           # >= this cosine score = same known speaker
                                        # (higher -> more speakers, lower -> fewer)
MIN_SPK_DURATION = 1.0                  # phrases shorter than this reuse the last speaker

CHUNK_FRAMES = max(1, int(SAMPLE_RATE * CHUNK_SECONDS))
PREROLL_CHUNKS = max(1, round(PREROLL / CHUNK_SECONDS))


# ---------------------------------------------------------------------------
# Live speaker matching
# ---------------------------------------------------------------------------
class SpeakerTracker:
    """Assigns a stable 'Speaker N' to each remote phrase by voiceprint match."""

    def __init__(self, emb_model):
        import sherpa_onnx as so
        self._so = so
        self.ext = so.SpeakerEmbeddingExtractor(
            so.SpeakerEmbeddingExtractorConfig(model=str(emb_model), num_threads=1))
        self.reset()

    def reset(self):
        self.mgr = self._so.SpeakerEmbeddingManager(self.ext.dim)
        self.count = 0
        self.last = "Them"

    def _embed(self, audio):
        s = self.ext.create_stream()
        s.accept_waveform(SAMPLE_RATE, audio)
        s.input_finished()
        return self.ext.compute(s)

    def assign(self, audio):
        # too short to fingerprint reliably -> attribute to the last speaker
        if audio.size / SAMPLE_RATE < MIN_SPK_DURATION:
            return self.last if self.last != "Them" else "Them"
        emb = self._embed(audio)
        name = self.mgr.search(emb, SPEAKER_MATCH_THRESHOLD)
        if not name:
            self.count += 1
            name = f"Speaker {self.count}"
            self.mgr.add(name, emb)
        self.last = name
        return name


def transcribe_utterance(model, audio):
    """Transcribe one endpointed phrase (fast settings for low latency)."""
    if audio.size == 0:
        return ""
    segments, _ = model.transcribe(
        audio, beam_size=5, vad_filter=False, condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segments if s.text.strip()).strip()


# ---------------------------------------------------------------------------
# One capture channel with energy-based endpointing
# ---------------------------------------------------------------------------
class LiveChannel(threading.Thread):
    """Records one source, and whenever a phrase ends, drops (label, audio)
    onto the shared work queue for transcription."""

    def __init__(self, mic_factory, label, work_q, stop_event, end_sil_chunks):
        super().__init__(daemon=True)
        self.mic_factory = mic_factory
        self.label = label
        self.q = work_q
        self.stop_event = stop_event
        self.end_sil_chunks = end_sil_chunks
        self.error = None

    def run(self):
        try:
            mic = self.mic_factory()
            preroll = deque(maxlen=PREROLL_CHUNKS)
            buf = []
            in_speech = False
            silence = 0
            noise = MIN_RMS
            with mic.recorder(samplerate=SAMPLE_RATE, channels=1) as rec:
                while not self.stop_event.is_set():
                    data = rec.record(numframes=CHUNK_FRAMES)
                    mono = data.mean(axis=1) if data.ndim > 1 else data
                    mono = mono.astype(np.float32)
                    rms = float(np.sqrt(np.mean(mono ** 2))) if mono.size else 0.0

                    threshold = max(MIN_RMS, noise * SPEECH_MULT)
                    if rms > threshold:
                        if not in_speech:
                            in_speech = True
                            buf = list(preroll)      # include the lead-in
                        buf.append(mono)
                        silence = 0
                    else:
                        noise = 0.9 * noise + 0.1 * rms   # adapt to background
                        preroll.append(mono)
                        if in_speech:
                            buf.append(mono)
                            silence += 1
                            if silence >= self.end_sil_chunks:
                                self._flush(buf)
                                buf, in_speech, silence = [], False, 0

                    if in_speech and len(buf) * CHUNK_SECONDS >= MAX_UTTERANCE:
                        self._flush(buf)
                        buf, in_speech, silence = [], False, 0

                if in_speech:            # flush whatever was mid-phrase at Stop
                    self._flush(buf)
        except Exception as exc:
            self.error = exc

    def _flush(self, chunks):
        if not chunks:
            return
        audio = np.concatenate(chunks).astype(np.float32)
        if audio.size / SAMPLE_RATE >= MIN_SPEECH:
            self.q.put((self.label, audio))


def make_loopback():
    speaker = sc.default_speaker()
    return sc.get_microphone(id=str(speaker.name), include_loopback=True)


def make_mic():
    return sc.default_microphone()


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class LiveApp:
    _SPEAKER_COLORS = ["#1f4fd8", "#b8860b", "#8e44ad", "#c0392b", "#16a085", "#d35400"]

    def __init__(self, root):
        self.root = root
        self.model = None
        self.tracker = None
        self.recording = False
        self.channels = []
        self.stop_event = None
        self.work_q = None
        self.session = []            # [(label, text), ...] for saving
        self._speaker_tag_count = 0
        self._last_written_label = None   # for coalescing a speaker's phrases

        self.speakers = []
        self.mics = []

        root.title("Live Transcriber")
        root.geometry("700x620")

        self.toggle_btn = tk.Button(
            root, text="● Start", font=("Segoe UI", 14, "bold"),
            width=14, height=2, state=tk.DISABLED, command=self.toggle)
        self.toggle_btn.pack(pady=(14, 6))

        # -- device pickers: choose exactly which output/mic to capture --
        from tkinter import ttk
        dev = tk.LabelFrame(root, text="Devices", font=("Segoe UI", 9))
        dev.pack(fill=tk.X, padx=12, pady=(0, 4))
        tk.Label(dev, text="Listen to call audio (output):",
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.out_combo = ttk.Combobox(dev, state="readonly", width=44)
        self.out_combo.grid(row=0, column=1, padx=4, pady=2)
        tk.Label(dev, text="Your microphone (input):",
                 font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.mic_combo = ttk.Combobox(dev, state="readonly", width=44)
        self.mic_combo.grid(row=1, column=1, padx=4, pady=2)
        tk.Button(dev, text="Refresh", command=self._refresh_devices).grid(
            row=0, column=2, rowspan=2, padx=6)
        self._refresh_devices()

        self.status = tk.Label(root, text="Starting up...", font=("Segoe UI", 10))
        self.status.pack(pady=(4, 0))

        from tkinter import scrolledtext
        self.output = scrolledtext.ScrolledText(
            root, wrap=tk.WORD, font=("Consolas", 11), height=20)
        self.output.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        self.output.tag_config("Me", foreground="#0a7d2c")
        self.output.tag_config("Them", foreground="#1f4fd8")
        self.output.tag_config("sys", foreground="#888888")

        self._ui_queue = queue.Queue()
        self.root.after(80, self._drain_ui_queue)
        threading.Thread(target=self._load_thread, daemon=True).start()

    # -- thread-safe UI helpers --------------------------------------------
    def _post(self, fn):
        self._ui_queue.put(fn)

    def _drain_ui_queue(self):
        while True:
            try:
                fn = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            fn()
        self.root.after(80, self._drain_ui_queue)

    def set_status(self, text):
        self._post(lambda: self.status.config(text=text))

    # -- device selection ---------------------------------------------------
    def _refresh_devices(self):
        """(Re)enumerate output/mic devices and preselect the system defaults."""
        try:
            self.speakers = sc.all_speakers()
            self.mics = sc.all_microphones()
            def_spk = sc.default_speaker().name
            def_mic = sc.default_microphone().name
        except Exception:
            self.speakers, self.mics = [], []
            return
        self.out_combo["values"] = [s.name for s in self.speakers]
        self.mic_combo["values"] = [m.name for m in self.mics]
        self._preselect(self.out_combo, self.speakers, def_spk)
        self._preselect(self.mic_combo, self.mics, def_mic)

    @staticmethod
    def _preselect(combo, devices, default_name):
        for i, d in enumerate(devices):
            if d.name == default_name:
                combo.current(i)
                return
        if devices:
            combo.current(0)

    def _selected_loopback(self):
        i = self.out_combo.current()
        spk = self.speakers[i] if 0 <= i < len(self.speakers) else sc.default_speaker()
        return sc.get_microphone(id=str(spk.name), include_loopback=True)

    def _selected_mic(self):
        i = self.mic_combo.current()
        return self.mics[i] if 0 <= i < len(self.mics) else sc.default_microphone()

    def _ensure_tag(self, label):
        if label == "sys" or label in ("Me", "Them"):
            return label
        if label not in self.output.tag_names():
            colour = self._SPEAKER_COLORS[self._speaker_tag_count % len(self._SPEAKER_COLORS)]
            self.output.tag_config(label, foreground=colour)
            self._speaker_tag_count += 1
        return label

    def write_live(self, label, text):
        """Append a phrase. Consecutive phrases from the same speaker are joined
        into one flowing paragraph rather than each starting a new labelled line."""
        def _do():
            if label == "sys":
                if self._last_written_label is not None:
                    self.output.insert(tk.END, "\n")
                self.output.insert(tk.END, text, "sys")
                self._last_written_label = "sys"
            elif label == self._last_written_label:
                self.output.insert(tk.END, " " + text)      # continue the paragraph
            else:
                if self._last_written_label is not None:
                    self.output.insert(tk.END, "\n")
                self.output.insert(tk.END, f"{label}: ", self._ensure_tag(label))
                self.output.insert(tk.END, text)
                self._last_written_label = label
            self.output.see(tk.END)
        self._post(_do)

    # -- startup ------------------------------------------------------------
    def _load_thread(self):
        try:
            self.model = core.load_model(self.set_status)
            try:
                if core.DIAR_EMB_MODEL.exists():
                    self.set_status("Loading speaker-ID model...")
                    self.tracker = SpeakerTracker(core.DIAR_EMB_MODEL)
            except Exception:
                self.tracker = None
            extra = " + live speaker ID" if self.tracker else " (Me/Them only)"
            self.set_status(f"Ready{extra}. Press Start.")
            self._post(lambda: self.toggle_btn.config(state=tk.NORMAL))
        except Exception:
            self.set_status("Model load failed -- see console (run_live_debug.bat).")

    # -- start / stop -------------------------------------------------------
    def toggle(self):
        self.stop() if self.recording else self.start()

    def start(self):
        # grab the chosen devices now, on the UI thread (Tk is not thread-safe)
        try:
            loop_dev = self._selected_loopback()
            mic_dev = self._selected_mic()
        except Exception as exc:
            from tkinter import messagebox
            messagebox.showerror("Audio error", f"Could not open the selected devices:\n{exc}")
            return

        self.session = []
        self.stop_event = threading.Event()
        self.work_q = queue.Queue()
        if self.tracker:
            self.tracker.reset()
            self._speaker_tag_count = 0

        them_sil = max(1, round(END_SILENCE_THEM / CHUNK_SECONDS))
        me_sil = max(1, round(END_SILENCE_ME / CHUNK_SECONDS))
        self.channels = [
            LiveChannel(lambda: loop_dev, "Them", self.work_q, self.stop_event, them_sil),
            LiveChannel(lambda: mic_dev, "Me", self.work_q, self.stop_event, me_sil),
        ]
        for c in self.channels:
            c.start()
        threading.Thread(target=self._worker_loop, daemon=True).start()

        self.recording = True
        self.out_combo.config(state=tk.DISABLED)
        self.mic_combo.config(state=tk.DISABLED)
        self.toggle_btn.config(text="■ Stop", bg="#c0392b", fg="white")
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.write_live("sys", f"--- live session started {stamp} (audio never saved) ---")
        self.write_live("sys", f"Listening to output: {loop_dev.name}")
        self.set_status("Listening... text appears as people finish speaking.")

    def stop(self):
        self.recording = False
        self.toggle_btn.config(text="● Start", bg="SystemButtonFace", fg="black",
                               state=tk.DISABLED)
        self.set_status("Finishing up...")
        if self.stop_event:
            self.stop_event.set()   # channels flush + worker drains, then finishes

    def _worker_loop(self):
        try:
            while not (self.stop_event.is_set() and self.work_q.empty()):
                try:
                    label, audio = self.work_q.get(timeout=0.2)
                except queue.Empty:
                    continue
                text = transcribe_utterance(self.model, audio)
                if not text:
                    continue
                if label == "Them" and self.tracker is not None:
                    label = self.tracker.assign(audio)
                self.session.append((label, text))
                self.write_live(label, text)
        except Exception:
            self.write_live("sys", "WORKER ERROR:\n" + traceback.format_exc())
        finally:
            self._post(self._finish_session)

    def _finish_session(self):
        for c in self.channels:
            if c.error:
                self.write_live("sys", f"Capture issue on '{c.label}': {c.error}")
        if core.SAVE_TRANSCRIPTS and self.session:
            self._save()
        self.toggle_btn.config(state=tk.NORMAL)
        self.out_combo.config(state="readonly")
        self.mic_combo.config(state="readonly")
        self.set_status("Stopped. Press Start to go again.")

    def _save(self):
        core.TRANSCRIPT_DIR.mkdir(exist_ok=True)
        fname = core.TRANSCRIPT_DIR / f"live-{datetime.datetime.now():%Y%m%d-%H%M%S}.txt"
        # group consecutive same-speaker phrases and apply list formatting
        turns = core.group_turns([(i, lbl, txt) for i, (lbl, txt) in enumerate(self.session)])
        with open(fname, "w", encoding="utf-8") as fh:
            fh.write(f"Live transcript -- {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")
            fh.write("=" * 40 + "\n\n")
            for label, text in turns:
                lines = text.split("\n")
                if len(lines) == 1:
                    fh.write(f"{label}: {lines[0]}\n")
                else:
                    fh.write(f"{label}:\n")
                    for ln in lines:
                        fh.write(f"    {ln}\n")
        self.write_live("sys", f"Saved transcript to: {fname.resolve()}")


def main():
    root = tk.Tk()
    LiveApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
