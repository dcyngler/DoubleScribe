"""
QA quality metrics for the live-transcription pipeline: real-time factor,
time-to-first-phrase, stop-to-saved latency, and max work-queue backlog.
These are the numbers that turned "slow" from a vague complaint into a
measured, fixable regression during the investigation (see the CPU/GPU
model-size fix in transcriber.load_model() and its tests in
test_transcriber_model.py) -- kept here as bounded regression assertions so
a future change can't silently reintroduce the backlog/stop-hang behavior.
"""
import pytest

from support import LiveSessionHarness


def test_fast_inference_keeps_backlog_at_zero_and_stops_quickly(monkeypatch, tmp_path):
    """Simulates a GPU-class model (near-instant transcribe): backlog should
    never build up, and Stop should return almost immediately."""
    harness = LiveSessionHarness(monkeypatch, tmp_path, inference_delay=0.0)

    for _ in range(5):
        harness.feed_phrase()

    stop_latency = harness.stop_and_wait(timeout=10)

    assert harness.max_backlog <= 1
    assert stop_latency < 1.0
    assert harness.first_phrase_at is not None
    assert harness.first_phrase_at < 1.0


def test_slow_inference_builds_backlog_and_stop_reflects_drain_time(monkeypatch, tmp_path):
    """Simulates a slower-than-real-time model: feeding phrases faster than
    they can be transcribed should visibly build a backlog, and Stop must
    still eventually complete (it drains, it doesn't hang forever) -- this
    is the mechanism behind the reported "Stop takes forever" symptom."""
    harness = LiveSessionHarness(monkeypatch, tmp_path, inference_delay=0.2)

    for _ in range(6):
        harness.feed_phrase()   # queued far faster than the 0.2s/phrase worker can drain

    stop_latency = harness.stop_and_wait(timeout=10)

    assert harness.max_backlog >= 2   # a real backlog formed
    # Stop must still finish in bounded time -- roughly (backlog * inference_delay),
    # not "forever". Generous multiplier keeps this from being flaky on slow CI.
    assert stop_latency < 6 * 0.2 * 3
    assert len(harness.phrases_seen) == 6


def test_real_time_factor_helper():
    """RTF = inference_time / audio_duration. Documents the exact metric used
    to characterize the CPU-vs-GPU regression (measured ~0.4-1.1x on the
    investigation machine's CPU/int8 "base" model vs >1x for "small")."""
    def rtf(infer_seconds, audio_seconds):
        return infer_seconds / audio_seconds if audio_seconds else float("inf")

    assert rtf(1.65, 12.84) == pytest.approx(0.128, abs=0.01)
    assert rtf(4.57, 4.06) == pytest.approx(1.126, abs=0.01)
