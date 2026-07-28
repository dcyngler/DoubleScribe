"""
Unit tests for app/engine.py -- the headless live-transcription controller.

Covers the pieces implicated in the live-latency/stop-hang investigation:
turn grouping, cross-device duplicate suppression, and AUTO-vs-pinned device
selection (the original fan-out hypothesis -- ruled out on the dev machine
used for this investigation, since it only has one speaker + one mic, but
still a real risk on machines with more audio endpoints, so it's locked in
as a regression test here).
"""
import queue
import threading

import numpy as np
import pytest

import engine


# ---------------------------------------------------------------------------
# _group_turns
# ---------------------------------------------------------------------------
def test_group_turns_merges_consecutive_same_label():
    session = [("Me", "hello", False), ("Me", "there", False)]
    turns = engine._group_turns(session)
    assert turns == [("Me", "hello there")]


def test_group_turns_splits_on_label_change():
    session = [("Me", "hi", False), ("Them", "hey", False)]
    turns = engine._group_turns(session)
    assert turns == [("Me", "hi"), ("Them", "hey")]


def test_group_turns_voice_change_splits_same_label_run():
    """A 'Them' phrase flagged voice_change=True starts a new turn even though
    the label is unchanged -- a different remote voice gets its own bubble."""
    session = [
        ("Them", "first speaker", False),
        ("Them", "still first speaker", False),
        ("Them", "second speaker now", True),
    ]
    turns = engine._group_turns(session)
    assert turns == [
        ("Them", "first speaker still first speaker"),
        ("Them", "second speaker now"),
    ]


# ---------------------------------------------------------------------------
# _worker: cross-device duplicate suppression
# ---------------------------------------------------------------------------
def _make_engine(monkeypatch, transcribed_text="hello world"):
    eng = engine.LiveEngine()
    eng.model = object()  # never actually used -- transcribe_utterance is patched
    eng.work_q = queue.Queue()
    eng.stop_event = threading.Event()
    monkeypatch.setattr(engine.live, "transcribe_utterance", lambda model, audio: transcribed_text)
    return eng


def test_worker_suppresses_duplicate_phrase_same_label(monkeypatch):
    """Two devices captured under the same label (e.g. two 'Them' endpoints in
    AUTO mode both picking up the same call audio) shouldn't produce two bubbles."""
    eng = _make_engine(monkeypatch)
    audio = np.zeros(1600, dtype=np.float32)
    eng.work_q.put(("Them", audio))
    eng.work_q.put(("Them", audio))
    eng.stop_event.set()   # worker exits once the queue drains

    phrases = []
    eng.on_phrase = lambda label, text, voice_change=False: phrases.append((label, text))

    eng._worker()

    assert phrases == [("Them", "hello world")]


def test_worker_does_not_suppress_across_different_labels(monkeypatch):
    """Same text from 'Me' and 'Them' are different speakers saying the same
    thing -- both should come through."""
    eng = _make_engine(monkeypatch)
    audio = np.zeros(1600, dtype=np.float32)
    eng.work_q.put(("Me", audio))
    eng.work_q.put(("Them", audio))
    eng.stop_event.set()

    phrases = []
    eng.on_phrase = lambda label, text, voice_change=False: phrases.append((label, text))

    eng._worker()

    assert phrases == [("Me", "hello world"), ("Them", "hello world")]


def test_worker_reports_backlog_while_draining_after_stop(monkeypatch):
    """Regression test for the Stop-hang fix: while stop_event is set and there's
    still a queued backlog, the worker should push a progress status instead of
    processing silently until _finish() returns."""
    eng = _make_engine(monkeypatch, transcribed_text="")  # empty text -> skipped, only status matters
    audio = np.zeros(1600, dtype=np.float32)
    eng.work_q.put(("Me", audio))
    eng.work_q.put(("Me", audio))
    eng.stop_event.set()

    statuses = []
    eng.on_status = statuses.append

    eng._worker()

    assert any("more phrase" in s for s in statuses)
    assert statuses[-1] == "Finishing -- saving..."


# ---------------------------------------------------------------------------
# start(): AUTO vs pinned device selection (the original fan-out hypothesis)
# ---------------------------------------------------------------------------
class _FakeDevice:
    def __init__(self, name):
        self.name = name


class _FakeChannel:
    """Stands in for live.LiveChannel so start() can be tested without opening
    real audio streams or spawning real capture threads."""
    instances = []

    def __init__(self, mic_factory, label, work_q, stop_event, end_sil_chunks):
        self.label = label
        self.mic_factory = mic_factory
        _FakeChannel.instances.append(self)

    def start(self):
        pass

    def join(self, timeout=None):
        pass

    def is_alive(self):
        return False


@pytest.fixture
def fake_devices(monkeypatch):
    import soundcard as sc

    speakers = [_FakeDevice("Speaker A"), _FakeDevice("Speaker B"), _FakeDevice("Speaker C")]
    mics = [_FakeDevice("Mic A"), _FakeDevice("Mic B")]

    monkeypatch.setattr(sc, "all_speakers", lambda: speakers)
    monkeypatch.setattr(sc, "all_microphones", lambda: mics)
    monkeypatch.setattr(sc, "default_speaker", lambda: speakers[0])
    monkeypatch.setattr(sc, "default_microphone", lambda: mics[0])
    monkeypatch.setattr(sc, "get_microphone", lambda id, include_loopback=False: _FakeDevice(id))

    _FakeChannel.instances = []
    monkeypatch.setattr(engine.live, "LiveChannel", _FakeChannel)
    return speakers, mics


def test_auto_mode_opens_one_channel_per_device(fake_devices):
    speakers, mics = fake_devices
    eng = engine.LiveEngine()

    result = eng.start(out_index=-1, in_index=-1)

    assert result["auto"] is True
    assert len(_FakeChannel.instances) == len(speakers) + len(mics)
    assert sum(1 for c in _FakeChannel.instances if c.label == "Them") == len(speakers)
    assert sum(1 for c in _FakeChannel.instances if c.label == "Me") == len(mics)
    eng.stop_event.set()   # let the real worker thread exit its poll loop


def test_pinned_mode_opens_exactly_two_channels(fake_devices):
    eng = engine.LiveEngine()

    result = eng.start(out_index=0, in_index=0)

    assert result["auto"] is False
    assert len(_FakeChannel.instances) == 2
    labels = sorted(c.label for c in _FakeChannel.instances)
    assert labels == ["Me", "Them"]
    eng.stop_event.set()
