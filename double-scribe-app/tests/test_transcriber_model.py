"""
Regression tests for the CPU/GPU model-size split in transcriber.load_model().

This is the fix for the actual root cause found during the live-latency
investigation: on hardware with no usable CUDA GPU (e.g. an AMD-only laptop),
load_model() silently fell back to CPU/int8 while still requesting the
"small" model -- measured at ~0.4-1.1x real-time per utterance, which can't
keep two live channels (Me + Them) caught up over a full call, and produced
the reported "no live text" / "Stop hangs forever" symptoms. The fix uses a
smaller MODEL_SIZE_CPU ("base") whenever CPU is the device actually used,
on both the frozen (always-CPU) and dev-mode (CUDA-probe-failed) paths.
"""
import sys

import numpy as np
import pytest

import transcriber as core


class _FakeWhisperModel:
    """Stands in for faster_whisper.WhisperModel. `fail_devices` names devices
    whose construction should raise, simulating no GPU / broken CUDA."""

    def __init__(self, ref, device, compute_type, fail_devices=()):
        if device in fail_devices:
            raise RuntimeError(f"no {device} available")
        self.ref = ref
        self.device = device
        self.compute_type = compute_type

    def transcribe(self, audio, beam_size=1, **kw):
        return ([], None)


@pytest.fixture
def status_messages():
    return []


def _status_cb(messages):
    return messages.append


def test_dev_mode_prefers_gpu_with_small_model(monkeypatch, status_messages):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(core, "ensure_model", lambda size, cb: None)
    monkeypatch.setattr(
        core, "WhisperModel",
        lambda ref, device, compute_type: _FakeWhisperModel(ref, device, compute_type))

    model = core.load_model(_status_cb(status_messages))

    assert model.device == "cuda"
    assert model.ref == core.MODEL_SIZE_GPU
    assert core.ACTIVE_MODEL_SIZE == core.MODEL_SIZE_GPU
    assert core.MODEL_SIZE_GPU == "small"


def test_dev_mode_falls_back_to_cpu_with_smaller_model_when_no_gpu(monkeypatch, status_messages):
    """This is the exact scenario measured on the investigation machine: no
    CUDA-capable GPU, so the cuda attempt raises and CPU is used -- it must
    use MODEL_SIZE_CPU ("base"), not MODEL_SIZE_GPU ("small")."""
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(core, "ensure_model", lambda size, cb: None)
    monkeypatch.setattr(
        core, "WhisperModel",
        lambda ref, device, compute_type: _FakeWhisperModel(
            ref, device, compute_type, fail_devices=("cuda",)))

    model = core.load_model(_status_cb(status_messages))

    assert model.device == "cpu"
    assert model.ref == core.MODEL_SIZE_CPU
    assert core.ACTIVE_MODEL_SIZE == core.MODEL_SIZE_CPU
    assert core.MODEL_SIZE_CPU != "small"   # must actually be smaller than "small"


def test_frozen_build_always_uses_cpu_with_smaller_model(monkeypatch, status_messages):
    """The packaged build never attempts CUDA at all (transcriber.py's own
    frozen-CPU-only policy) -- it must go straight to MODEL_SIZE_CPU."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(core, "ensure_model", lambda size, cb: None)
    monkeypatch.setattr(
        core, "WhisperModel",
        lambda ref, device, compute_type: _FakeWhisperModel(ref, device, compute_type))

    model = core.load_model(_status_cb(status_messages))

    assert model.device == "cpu"
    assert model.ref == core.MODEL_SIZE_CPU
    assert core.ACTIVE_MODEL_SIZE == core.MODEL_SIZE_CPU


def test_load_model_raises_when_every_device_fails(monkeypatch, status_messages):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(core, "ensure_model", lambda size, cb: None)
    monkeypatch.setattr(
        core, "WhisperModel",
        lambda ref, device, compute_type: _FakeWhisperModel(
            ref, device, compute_type, fail_devices=("cuda", "cpu")))

    with pytest.raises(RuntimeError):
        core.load_model(_status_cb(status_messages))
