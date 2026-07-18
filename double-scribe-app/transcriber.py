"""
Local audio transcriber.

Captures your computer's audio output (what you hear) and your microphone
(what you say) while toggled on, then transcribes both locally with Whisper
when you toggle off. Nothing is uploaded, and the audio is discarded after
transcription -- only the text transcript is kept.

The two sources are transcribed separately so each line is labelled:
    Me        -> came from your microphone (you)
    Speaker N -> a distinct voice on your speakers/headphones (a remote person),
                 separated by on-device speaker identification. Falls back to a
                 single "Them" label if the speaker-ID models are unavailable.

Everything runs offline. No internet, no cloud, no API keys.
"""

import os
import sys
import threading
import queue
import datetime
import traceback
from pathlib import Path


def _add_nvidia_dll_dirs():
    """If the NVIDIA CUDA pip wheels are installed, put their DLLs on the
    search path so GPU transcription can find cublas/cudnn. Harmless if absent.

    Both steps matter: add_dll_directory covers Python-level loads, while
    prepending to PATH is what CTranslate2's own loader actually searches."""
    try:
        import importlib.util
        spec = importlib.util.find_spec("nvidia")
        if spec is None or not spec.submodule_search_locations:
            return  # NVIDIA wheels not installed -- CPU will be used
        nvidia = Path(list(spec.submodule_search_locations)[0])
        bins = [str(sub / "bin") for sub in nvidia.iterdir() if (sub / "bin").is_dir()]
        if bins:
            os.environ["PATH"] = os.pathsep.join(bins) + os.pathsep + os.environ.get("PATH", "")
            for b in bins:
                os.add_dll_directory(b)
    except Exception:
        pass


_add_nvidia_dll_dirs()

# Lightweight startup log so we can diagnose hangs even under pythonw (no console).
_LOG_FILE = Path(__file__).parent / "startup.log"


def _log(msg):
    try:
        import datetime as _dt
        stamp = _dt.datetime.now().strftime("%H:%M:%S")
        with open(_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp}  {msg}\n")
    except Exception:
        pass


import numpy as np
import soundcard as sc
import tkinter as tk
from tkinter import scrolledtext, messagebox

from faster_whisper import WhisperModel


# ---------------------------------------------------------------------------
# Packaging awareness -- where assets and user data live
# ---------------------------------------------------------------------------
# In development everything sits in the source tree (unchanged behaviour). In a
# PyInstaller build, read-only assets (the bundled Whisper model) live under
# sys._MEIPASS, while user data (transcripts, index.json) must go to a writable
# per-user location -- never inside the install folder.
def _resource_dir():
    """Read-only bundled assets (sys._MEIPASS when frozen, else source tree)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).parent


def _data_dir():
    """Writable location for transcripts + index.json."""
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "DoubleScribe"
        base.mkdir(parents=True, exist_ok=True)
        return base
    return Path(__file__).parent


RESOURCE_DIR = _resource_dir()
DATA_DIR = _data_dir()

if getattr(sys, "frozen", False):
    # Belt-and-braces: the packaged build is fully offline; never reach out to
    # the HuggingFace hub even if a model name (rather than a path) is used.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# ---------------------------------------------------------------------------
# Settings -- tweak these to taste
# ---------------------------------------------------------------------------
MODEL_SIZE = "small"        # "tiny", "base", "small", "medium", "large-v3"
                            # larger = more accurate but slower. "small" is a good start.
SAMPLE_RATE = 16000         # Whisper expects 16 kHz; soundcard resamples for us.
CHUNK_SECONDS = 0.1         # how often we pull audio from the device (100 ms)
SAVE_TRANSCRIPTS = True     # write each transcript to a .txt next to this script
KEEP_AUDIO = False          # leave False: audio is never written to disk
TRANSCRIPT_DIR = DATA_DIR / "transcripts"
INDEX_PATH = DATA_DIR / "index.json"   # library metadata (owned by app/store.py)
BUNDLED_WHISPER = RESOURCE_DIR / "whisper-small"   # offline model, present in packaged build

# -- Speaker identification (diarisation) ----------------------------------
# Splits the "Them" channel into Speaker 1 / Speaker 2 / ... using small ONNX
# models (no PyTorch, no login). If the models are missing it silently falls
# back to a single "Them" label.
ENABLE_DIARIZATION = True
NUM_SPEAKERS = 0            # 0 = auto-detect; or set a fixed number of remote speakers
DIAR_THRESHOLD = 0.7        # auto-detect only: HIGHER merges more (fewer speakers),
                            # lower splits more (more speakers). Ignored when you
                            # set a fixed speaker count.
MODELS_DIR = RESOURCE_DIR / "models"
DIAR_SEG_MODEL = MODELS_DIR / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
DIAR_EMB_MODEL = MODELS_DIR / "nemo_en_titanet_small.onnx"

# ---------------------------------------------------------------------------
# Audio capture
# ---------------------------------------------------------------------------
class StreamRecorder(threading.Thread):
    """Records one audio source into memory until stopped."""

    def __init__(self, mic_obj, label):
        super().__init__(daemon=True)
        self.mic = mic_obj
        self.label = label
        self.frames = []
        self._running = threading.Event()
        self._running.set()
        self._error = None

    def run(self):
        try:
            chunk = max(1, int(SAMPLE_RATE * CHUNK_SECONDS))
            with self.mic.recorder(samplerate=SAMPLE_RATE, channels=1) as rec:
                while self._running.is_set():
                    self.frames.append(rec.record(numframes=chunk).copy())
        except Exception as exc:  # surfaced to the UI later
            self._error = exc

    def stop(self):
        self._running.clear()

    def get_audio(self):
        """Return the recorded audio as a 1-D float32 array at 16 kHz."""
        if not self.frames:
            return np.zeros(0, dtype=np.float32)
        audio = np.concatenate(self.frames, axis=0)
        if audio.ndim > 1:            # collapse to mono
            audio = audio.mean(axis=1)
        return audio.astype(np.float32)


def make_loopback_recorder():
    """Recorder for the default speaker's output (what you hear)."""
    speaker = sc.default_speaker()
    loopback = sc.get_microphone(id=str(speaker.name), include_loopback=True)
    return StreamRecorder(loopback, "Them")


def make_mic_recorder():
    """Recorder for the default microphone (what you say)."""
    return StreamRecorder(sc.default_microphone(), "Me")


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------
def load_model(status_cb):
    """Load Whisper, preferring the GPU and falling back to CPU.

    Crucially this runs a tiny test transcription on each device: loading a
    model on CUDA can succeed even when the GPU compute libraries are missing,
    and the failure only shows up at inference time. Probing here means we fall
    back to CPU cleanly instead of crashing the first time you press Stop.
    """
    probe = (np.random.randn(8000).astype(np.float32)) * 0.01  # ~0.5s of quiet noise
    # Packaged build ships the model on disk and is CPU-only (no CUDA wheels
    # bundled); development loads by name and prefers the GPU.
    ref = str(BUNDLED_WHISPER) if (BUNDLED_WHISPER / "model.bin").exists() else MODEL_SIZE
    devices = (("cpu", "int8"),) if getattr(sys, "frozen", False) \
        else (("cuda", "float16"), ("cpu", "int8"))
    for device, compute in devices:
        try:
            status_cb(f"Loading Whisper '{MODEL_SIZE}' on {device.upper()}...")
            model = WhisperModel(ref, device=device, compute_type=compute)
            list(model.transcribe(probe, beam_size=1)[0])  # force real inference
            status_cb(f"Ready (running on {device.upper()}). Press Start.")
            return model
        except Exception:
            continue
    raise RuntimeError("Could not load the Whisper model on GPU or CPU.")


def transcribe_stream(model, audio):
    """Return a list of (start, end, text) segments for one audio source."""
    if audio.size == 0 or float(np.abs(audio).max()) < 1e-4:
        return []  # empty or silent
    segments, _ = model.transcribe(audio, vad_filter=True, beam_size=5)
    out = []
    for seg in segments:
        text = seg.text.strip()
        if text:
            out.append((seg.start, seg.end, text))
    return out


# ---------------------------------------------------------------------------
# Speaker identification (diarisation) -- separates voices on the "Them" channel
# ---------------------------------------------------------------------------
class Diarizer:
    """Wraps sherpa-onnx offline speaker diarisation (ONNX, CPU)."""

    def __init__(self, seg_model, emb_model, num_speakers=0, threshold=0.5):
        import sherpa_onnx as so
        self._so = so
        self.seg_model = seg_model
        self.emb_model = emb_model
        self.threshold = threshold
        self.num_speakers = num_speakers
        self.sd = self._build(num_speakers)

    def _build(self, num_speakers):
        so = self._so
        clustering = so.FastClusteringConfig(
            num_clusters=(num_speakers if num_speakers and num_speakers > 0 else -1),
            threshold=self.threshold,
        )
        cfg = so.OfflineSpeakerDiarizationConfig(
            segmentation=so.OfflineSpeakerSegmentationModelConfig(
                pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=self.seg_model)),
            embedding=so.SpeakerEmbeddingExtractorConfig(model=self.emb_model),
            clustering=clustering,
            min_duration_on=0.3,
            min_duration_off=0.5,
        )
        return so.OfflineSpeakerDiarization(cfg)

    def set_num_speakers(self, n):
        """Rebuild only if the requested speaker count changed (cheap models)."""
        if n != self.num_speakers:
            self.num_speakers = n
            self.sd = self._build(n)

    def diarize(self, audio):
        """Return [(start, end, speaker_index), ...] sorted by start time, with
        speaker indices renumbered 0,1,2,... in order of first appearance so the
        labels come out as Speaker 1, 2, 3 with no gaps."""
        res = self.sd.process(audio).sort_by_start_time()
        remap = {}
        out = []
        for s in res:
            if s.speaker not in remap:
                remap[s.speaker] = len(remap)
            out.append((s.start, s.end, remap[s.speaker]))
        return out


def load_diarizer(status_cb):
    """Build the diariser, or return None (falling back to a single 'Them')."""
    if not ENABLE_DIARIZATION:
        return None
    if not (DIAR_SEG_MODEL.exists() and DIAR_EMB_MODEL.exists()):
        status_cb("Speaker-ID models not found -- using Me/Them only.")
        return None
    try:
        status_cb("Loading speaker-ID models...")
        return Diarizer(str(DIAR_SEG_MODEL), str(DIAR_EMB_MODEL), NUM_SPEAKERS, DIAR_THRESHOLD)
    except Exception as exc:
        status_cb(f"Speaker ID unavailable ({exc}) -- using Me/Them only.")
        return None


def label_segments(segments, diar):
    """Tag each (start, end, text) with the speaker whose diarisation span
    overlaps it most. Falls back to 'Them' when no speaker overlaps."""
    out = []
    for s_start, s_end, text in segments:
        best, best_overlap = None, 0.0
        for d_start, d_end, spk in diar:
            overlap = min(s_end, d_end) - max(s_start, d_start)
            if overlap > best_overlap:
                best_overlap, best = overlap, spk
        label = f"Speaker {best + 1}" if best is not None else "Them"
        out.append((s_start, label, text))
    return out


def merge_transcripts(*segment_lists):
    """Interleave segments from both sources in chronological order."""
    merged = []
    for segs in segment_lists:
        merged.extend(segs)
    merged.sort(key=lambda s: s[0])
    return merged


# Spoken numbers -> digits, for detecting dictated lists.
_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "firstly": 1, "secondly": 2, "thirdly": 3, "fourthly": 4, "fifthly": 5,
}
_LIST_PREFIXES = {"point", "number", "step", "item"}


def format_dictated_lists(text):
    """Turn a spoken enumeration into a numbered list.

    Only number words that arrive *in sequence* (1, then 2, then 3 ...) are
    treated as list markers, so stray numbers inside a sentence ("eight cheese")
    are ignored and ordinary speech is left untouched. If fewer than two markers
    are found, the original text is returned unchanged.
    """
    import re

    def at_boundary(pos):
        j = pos - 1
        while j >= 0 and text[j] in " \t\r\n":
            j -= 1
        return j < 0 or text[j] in ".,;:!?"

    tokens = list(re.finditer(r"[A-Za-z']+", text))
    markers = []        # (marker_start_char, marker_end_char, value)
    expected = 1
    for i, tok in enumerate(tokens):
        if _NUM_WORDS.get(tok.group().lower()) == expected:
            start = tok.start()
            has_prefix = i > 0 and tokens[i - 1].group().lower() in _LIST_PREFIXES
            if has_prefix:
                start = tokens[i - 1].start()  # absorb "Point" in "Point one"
            # only a marker if it starts a clause or carries a list prefix --
            # this stops mid-sentence numbers from being mistaken for markers
            if not (has_prefix or at_boundary(start)):
                continue
            markers.append((start, tok.end(), expected))
            expected += 1

    if len(markers) < 2:
        return text

    lines = []
    for k, (_, m_end, value) in enumerate(markers):
        seg_end = markers[k + 1][0] if k + 1 < len(markers) else len(text)
        content = text[m_end:seg_end].strip(" \t\r\n.,;:-")
        if content:
            lines.append(f"{value}. {content}")
    return "\n".join(lines) if lines else text


def group_turns(merged):
    """Group consecutive same-speaker segments into one turn, then apply
    dictated-list formatting to each turn. Returns a list of (label, text)."""
    turns = []
    for _, label, text in merged:
        if turns and turns[-1][0] == label:
            turns[-1][1].append(text)
        else:
            turns.append([label, [text]])
    return [(label, format_dictated_lists(" ".join(p.strip() for p in parts).strip()))
            for label, parts in turns]


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class TranscriberApp:
    def __init__(self, root):
        self.root = root
        self.model = None
        self.diarizer = None
        self.recorders = []
        self.recording = False
        self._req_speakers = NUM_SPEAKERS
        self._speaker_tag_count = 0

        root.title("Double Scribe")
        root.geometry("680x560")

        self.toggle_btn = tk.Button(
            root, text="● Start", font=("Segoe UI", 14, "bold"),
            width=14, height=2, state=tk.DISABLED, command=self.toggle,
        )
        self.toggle_btn.pack(pady=(14, 6))

        # remote-speaker count: blank/auto lets the model decide
        ctrl = tk.Frame(root)
        ctrl.pack()
        tk.Label(ctrl, text="Remote speakers (blank = auto):",
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self.spk_var = tk.StringVar(value="auto")
        tk.Entry(ctrl, textvariable=self.spk_var, width=6).pack(side=tk.LEFT, padx=6)

        self.status = tk.Label(root, text="Starting up...", font=("Segoe UI", 10))
        self.status.pack(pady=(4, 0))

        self.output = scrolledtext.ScrolledText(
            root, wrap=tk.WORD, font=("Consolas", 11), height=20,
        )
        self.output.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        self.output.tag_config("Me", foreground="#0a7d2c")
        self.output.tag_config("Them", foreground="#1f4fd8")
        self.output.tag_config("sys", foreground="#888888")

        # status updates from worker threads land here
        self._ui_queue = queue.Queue()
        self.root.after(100, self._drain_ui_queue)

        # load the model off the UI thread so the window stays responsive
        threading.Thread(target=self._load_model_thread, daemon=True).start()

    # palette cycled through for Speaker 1, Speaker 2, ...
    _SPEAKER_COLORS = ["#1f4fd8", "#b8860b", "#8e44ad", "#c0392b", "#16a085", "#d35400"]

    def _ensure_tag(self, label):
        """Return a text tag for a label, creating a coloured one for new speakers."""
        if label == "sys" or label in ("Me", "Them"):
            return label
        if label not in self.output.tag_names():
            colour = self._SPEAKER_COLORS[self._speaker_tag_count % len(self._SPEAKER_COLORS)]
            self.output.tag_config(label, foreground=colour)
            self._speaker_tag_count += 1
        return label

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
        self.root.after(100, self._drain_ui_queue)

    def set_status(self, text):
        self._post(lambda: self.status.config(text=text))

    def write_line(self, label, text):
        def _do():
            self.output.insert(tk.END, f"{label}: ", label if label in ("Me", "Them") else "sys")
            self.output.insert(tk.END, f"{text}\n")
            self.output.see(tk.END)
        self._post(_do)

    def write_turn(self, label, text):
        """Write one speaker turn; multi-line (list) turns are indented."""
        def _do():
            tag = self._ensure_tag(label)
            lines = text.split("\n")
            if len(lines) == 1:
                self.output.insert(tk.END, f"{label}: ", tag)
                self.output.insert(tk.END, f"{lines[0]}\n")
            else:
                self.output.insert(tk.END, f"{label}:\n", tag)
                for ln in lines:
                    self.output.insert(tk.END, f"    {ln}\n")
            self.output.see(tk.END)
        self._post(_do)

    # -- model loading ------------------------------------------------------
    def _load_model_thread(self):
        try:
            _log("load thread: started")
            self.model = load_model(self.set_status)
            _log("load thread: Whisper loaded")
            self.diarizer = load_diarizer(self.set_status)
            _log(f"load thread: diariser loaded = {self.diarizer is not None}")
            extra = " + speaker ID" if self.diarizer else ""
            self.set_status(f"Ready{extra}. Press Start.")
            self._post(lambda: self.toggle_btn.config(state=tk.NORMAL))
            _log("load thread: READY")
        except Exception:
            err = traceback.format_exc()
            _log("load thread: FAILED\n" + err)
            self.set_status("Model load failed -- see startup.log")
            self.write_line("sys", "STARTUP ERROR:\n" + err)

    # -- start / stop -------------------------------------------------------
    def toggle(self):
        if not self.recording:
            self.start()
        else:
            self.stop()

    def start(self):
        try:
            self.recorders = [make_loopback_recorder(), make_mic_recorder()]
        except Exception as exc:
            messagebox.showerror("Audio error", f"Could not open audio devices:\n{exc}")
            return
        for r in self.recorders:
            r.start()
        self.recording = True
        self.toggle_btn.config(text="■ Stop", bg="#c0392b", fg="white")
        self.set_status("Recording... (audio is held in memory, never saved)")

    def _parse_speakers(self):
        v = self.spk_var.get().strip().lower()
        if v in ("", "auto", "0"):
            return 0
        try:
            return max(0, int(v))
        except ValueError:
            return 0

    def stop(self):
        self.recording = False
        self._req_speakers = self._parse_speakers()  # read on UI thread
        self.toggle_btn.config(text="● Start", bg="SystemButtonFace", fg="black",
                               state=tk.DISABLED)
        self.set_status("Transcribing...")
        for r in self.recorders:
            r.stop()
        threading.Thread(target=self._transcribe_thread, daemon=True).start()

    def _transcribe_thread(self):
        try:
            self._do_transcribe()
        except Exception:
            err = traceback.format_exc()
            self.write_line("sys", "TRANSCRIPTION ERROR:\n" + err)
            self.set_status("Error during transcription -- see the window.")
        finally:
            self._post(lambda: self.toggle_btn.config(state=tk.NORMAL))

    def _do_transcribe(self):
        for r in self.recorders:
            r.join()  # wait for capture loops to finish

        for r in self.recorders:
            if r._error:
                self.write_line("sys", f"Capture issue on '{r.label}': {r._error}")

        if self.diarizer is not None:
            self.diarizer.set_num_speakers(self._req_speakers)

        seg_lists = []
        for r in self.recorders:
            audio = r.get_audio()
            self.set_status(f"Transcribing '{r.label}' ({audio.size/SAMPLE_RATE:.0f}s)...")
            segs = transcribe_stream(self.model, audio)  # (start, end, text)

            if r.label == "Them" and self.diarizer is not None and audio.size:
                self.set_status("Identifying speakers...")
                try:
                    diar = self.diarizer.diarize(audio)
                    labelled = label_segments(segs, diar)
                except Exception as exc:
                    self.write_line("sys", f"(speaker ID skipped: {exc})")
                    labelled = [(s, "Them", t) for s, _, t in segs]
            else:
                labelled = [(s, r.label, t) for s, _, t in segs]

            seg_lists.append(labelled)
            r.frames.clear()  # drop the audio from memory

        merged = merge_transcripts(*seg_lists)
        turns = group_turns(merged)

        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.write_line("sys", f"--- {stamp} ---")
        if not turns:
            self.write_line("sys", "(nothing transcribed -- no speech detected)")
        for label, text in turns:
            self.write_turn(label, text)

        if SAVE_TRANSCRIPTS:
            self._save_transcript(turns, stamp)

        self.set_status("Done. Press Start to record again.")

    def _save_transcript(self, turns, stamp):
        TRANSCRIPT_DIR.mkdir(exist_ok=True)
        fname = TRANSCRIPT_DIR / f"transcript-{datetime.datetime.now():%Y%m%d-%H%M%S}.txt"
        with open(fname, "w", encoding="utf-8") as fh:
            fh.write(f"Transcript -- {stamp}\n")
            fh.write("=" * 40 + "\n\n")
            if not turns:
                fh.write("(no speech detected)\n")
            for label, text in turns:
                lines = text.split("\n")
                if len(lines) == 1:
                    fh.write(f"{label}: {lines[0]}\n")
                else:
                    fh.write(f"{label}:\n")
                    for ln in lines:
                        fh.write(f"    {ln}\n")
        self.write_line("sys", f"Saved transcript to: {fname.resolve()}")


def main():
    _log("=== launch ===")
    root = tk.Tk()
    TranscriberApp(root)
    _log("window created, entering mainloop")
    root.mainloop()


if __name__ == "__main__":
    main()
