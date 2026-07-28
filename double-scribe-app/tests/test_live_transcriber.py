"""
Unit tests for live_transcriber.py's endpointing state machine and voice-change
detector -- shared by both the old Tkinter live app and the new app/engine.py,
so a regression here affects both.
"""
import threading

import numpy as np
import pytest

import live_transcriber as live


class _FakeRecorder:
    """Replays a fixed list of audio chunks, then sets stop_event so the
    LiveChannel thread exits cleanly instead of blocking on real audio I/O."""

    def __init__(self, frames, stop_event):
        self._frames = frames
        self._idx = 0
        self._stop_event = stop_event

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def record(self, numframes):
        if self._idx >= len(self._frames):
            self._stop_event.set()
            return np.zeros(numframes, dtype=np.float32)
        chunk = self._frames[self._idx]
        self._idx += 1
        return chunk


class _FakeMic:
    def __init__(self, frames, stop_event):
        self._frames = frames
        self._stop_event = stop_event

    def recorder(self, samplerate, channels):
        return _FakeRecorder(self._frames, self._stop_event)


def _silence(n=1):
    return [np.zeros(live.CHUNK_FRAMES, dtype=np.float32) for _ in range(n)]


def _speech(n=1, amplitude=0.05):
    return [np.full(live.CHUNK_FRAMES, amplitude, dtype=np.float32) for _ in range(n)]


def _run_channel(frames, label, end_sil_chunks, timeout=5):
    stop_event = threading.Event()
    work_q = __import__("queue").Queue()
    mic = _FakeMic(frames, stop_event)
    channel = live.LiveChannel(lambda: mic, label, work_q, stop_event, end_sil_chunks)
    channel.start()
    channel.join(timeout=timeout)
    assert not channel.is_alive(), "channel thread did not finish in time"
    assert channel.error is None, f"channel raised: {channel.error}"
    items = []
    while not work_q.empty():
        items.append(work_q.get_nowait())
    return items


def test_flushes_one_phrase_after_trailing_silence():
    me_sil = max(1, round(live.END_SILENCE_ME / live.CHUNK_SECONDS))
    frames = _silence(3) + _speech(5) + _silence(me_sil)

    items = _run_channel(frames, "Me", me_sil)

    assert len(items) == 1
    label, audio = items[0]
    assert label == "Me"
    assert audio.size / live.SAMPLE_RATE >= live.MIN_SPEECH


def test_flush_drops_audio_shorter_than_min_speech():
    """_flush() is the MIN_SPEECH gate itself -- tested directly rather than via
    the full run loop, since with realistic END_SILENCE_* settings the trailing
    silence chunks appended before any flush already exceed MIN_SPEECH, so a
    short initial speech burst alone can't exercise this path end-to-end."""
    stop_event = threading.Event()
    work_q = __import__("queue").Queue()
    channel = live.LiveChannel(lambda: None, "Me", work_q, stop_event, end_sil_chunks=10)

    too_short = [np.zeros(10, dtype=np.float32)]   # far under MIN_SPEECH duration
    channel._flush(too_short)

    assert work_q.empty()


def test_flush_keeps_audio_at_or_above_min_speech():
    stop_event = threading.Event()
    work_q = __import__("queue").Queue()
    channel = live.LiveChannel(lambda: None, "Me", work_q, stop_event, end_sil_chunks=10)

    long_enough = [np.zeros(int(live.SAMPLE_RATE * live.MIN_SPEECH) + 100, dtype=np.float32)]
    channel._flush(long_enough)

    assert work_q.qsize() == 1
    label, audio = work_q.get_nowait()
    assert label == "Me"


def test_them_channel_uses_its_own_shorter_silence_window():
    them_sil = max(1, round(live.END_SILENCE_THEM / live.CHUNK_SECONDS))
    assert them_sil < max(1, round(live.END_SILENCE_ME / live.CHUNK_SECONDS))
    frames = _silence(3) + _speech(5) + _silence(them_sil)

    items = _run_channel(frames, "Them", them_sil)

    assert len(items) == 1
    assert items[0][0] == "Them"


# ---------------------------------------------------------------------------
# VoiceChangeDetector -- deterministic invariants only (real embedding model,
# so we don't assert on which audio "sounds like" a different voice).
# ---------------------------------------------------------------------------
import transcriber as core  # noqa: E402

pytestmark_model = pytest.mark.skipif(
    not core.DIAR_EMB_MODEL.exists(),
    reason="voice-change model not present (models/nemo_en_titanet_small.onnx)")


@pytestmark_model
def test_voice_change_detector_first_phrase_never_flagged():
    detector = live.VoiceChangeDetector(core.DIAR_EMB_MODEL)
    audio = (np.random.randn(int(live.SAMPLE_RATE * 2)).astype(np.float32)) * 0.05
    assert detector.changed(audio) is False


@pytestmark_model
def test_voice_change_detector_too_short_phrase_never_flagged():
    detector = live.VoiceChangeDetector(core.DIAR_EMB_MODEL)
    short_audio = (np.random.randn(
        int(live.SAMPLE_RATE * (live.MIN_VOICE_CHANGE_DURATION - 0.1))).astype(np.float32)) * 0.05
    # seed a run first so _run_sum is not None
    detector.changed((np.random.randn(int(live.SAMPLE_RATE * 2)).astype(np.float32)) * 0.05)
    assert detector.changed(short_audio) is False
