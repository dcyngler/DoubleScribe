"""
Shared test harness: drives LiveEngine's real _worker / stop / _finish
machinery (the exact code path behind the "no live text" / "Stop hangs"
symptoms) without real audio devices or a real Whisper model. Used by both
the QA-metrics tests and the Gherkin/BDD acceptance specs so they measure the
same thing the same way.
"""
import datetime
import queue
import threading
import time

import numpy as np

import engine as engine_mod


class LiveSessionHarness:
    """inference_delay simulates how long the (patched) transcribe_utterance
    takes per phrase -- pass a laptop-CPU-like value to reproduce backlog
    growth, or ~0 to simulate a fast GPU keeping up in real time."""

    def __init__(self, monkeypatch, tmp_path, inference_delay=0.0):
        monkeypatch.setattr(engine_mod.core, "TRANSCRIPT_DIR", tmp_path / "transcripts")

        self.eng = engine_mod.LiveEngine()
        self.eng.model = object()
        self.eng.work_q = queue.Queue()
        self.eng.stop_event = threading.Event()
        self.eng.channels = []          # no real capture threads to join at stop
        self.eng.recording = True
        self.eng._start_ts = datetime.datetime.now()

        self.phrases_seen = []
        self.first_phrase_at = None
        self.saved_at = None
        self.max_backlog = 0
        self._t0 = time.monotonic()
        self._done = threading.Event()

        self._transcribe_count = 0

        def fake_transcribe(model, audio):
            if inference_delay:
                time.sleep(inference_delay)
            self._transcribe_count += 1
            # Unique text per call -- otherwise the engine's own (correct) same-label
            # duplicate-phrase suppression collapses repeated test phrases to one,
            # which would confound backlog/latency measurements with dedupe behavior.
            return f"phrase {self._transcribe_count}"

        monkeypatch.setattr(engine_mod.live, "transcribe_utterance", fake_transcribe)

        def on_phrase(label, text, voice_change=False):
            if self.first_phrase_at is None:
                self.first_phrase_at = time.monotonic() - self._t0
            self.phrases_seen.append((label, text))
        self.eng.on_phrase = on_phrase

        def on_saved(meta):
            self.saved_at = time.monotonic() - self._t0
            self._done.set()
        self.eng.on_saved = on_saved

        self.eng._worker_thread = threading.Thread(target=self.eng._worker, daemon=True)
        self.eng._worker_thread.start()
        self._poller = threading.Thread(target=self._poll_backlog, daemon=True)
        self._poller.start()

    def _poll_backlog(self):
        while not self._done.is_set():
            self.max_backlog = max(self.max_backlog, self.eng.work_q.qsize())
            time.sleep(0.01)

    def feed_phrase(self, label="Me", audio_seconds=1.0):
        audio = np.zeros(int(engine_mod.SAMPLE_RATE * audio_seconds), dtype=np.float32)
        self.eng.work_q.put((label, audio))

    def stop_and_wait(self, timeout=30):
        elapsed_before_stop = time.monotonic() - self._t0
        self.eng.stop()
        finished = self._done.wait(timeout=timeout)
        assert finished, "session never reached on_saved -- Stop hung past the test timeout"
        return self.saved_at - elapsed_before_stop   # stop-to-saved latency
