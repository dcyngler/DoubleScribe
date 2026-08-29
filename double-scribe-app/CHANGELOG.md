# Changelog

All notable changes to Double Scribe are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/).

When you cut a release, add an entry here **and** a matching short bullet
list in `app/release_notes.py` (that one drives the in-app "What's new"
modal; this file is the full human-readable log).

## [0.4.6] - 2026-08-29

### Added
- App settings now shows "App Data Directory" and "Log Directory" rows (under Source code),
  each with the resolved path and an Open button that opens it in Explorer -- makes it easier
  to find transcripts/settings or the startup log without knowing the `%LOCALAPPDATA%` path.

## [0.4.5] - 2026-07-29

### Fixed
- Live transcription could lag well behind speech and "Stop" could hang for a long time on
  machines without a working CUDA GPU. `load_model()` was falling back to CPU/int8 while still
  requesting the "small" Whisper model, which measured at roughly 0.4-1.1x real time per
  utterance -- not enough headroom for two concurrent live channels (Me + Them) to stay caught
  up over a call, so a backlog built up silently and Stop had to drain it before it could save.
  The CPU fallback now uses a smaller "base" model (MODEL_SIZE_CPU), which runs several times
  faster on CPU/int8; the GPU path is unchanged.
- Stopping a live session now shows drain progress ("Finishing -- transcribing N more
  phrase(s)...") on the Stop button instead of a silent hang if any backlog remains.

### Added
- A pytest-based test suite (`tests/`) covering the live-transcription pipeline: turn grouping,
  cross-device duplicate suppression, AUTO-vs-pinned device selection, endpointing, voice-change
  detection, and the CPU/GPU model-size fallback, plus Gherkin/BDD acceptance specs and reusable
  QA-metric helpers (real-time factor, time-to-first-phrase, stop-to-saved latency, backlog
  depth). See `requirements-dev.txt`.

## [0.4.4] - 2026-07-28

### Fixed
- The live transcript panel only filled about half the window while recording. Recording start
  was hiding the inner card list but leaving its flex container in place, which still claimed
  half the row width next to the live panel. The whole list column is now hidden, so the live
  panel expands to fill the window.

## [0.4.3] - 2026-07-21

### Fixed
- The recording-consent notice is now versioned, so an install that already had it marked
  acknowledged (from an earlier build) will be shown it again once. This closes a gap where
  the gate could silently stay marked "acknowledged" across upgrades even if it hadn't
  actually been shown/re-read on the current build.

## [0.4.2] - 2026-07-21

### Added
- Donate button is now live, linking out to Stripe.

### Fixed
- Auto-updater now sanitizes the downloaded release's version string before using it in a
  temp file path, instead of trusting it as-is.

### Changed
- Website download link now redirects through GitHub's `releases/latest` alias so it always
  resolves to the newest signed build, and donation links point at the live Stripe page.

## [0.4.1] - 2026-07-20

### Added
- First public release of Double Scribe.
- Fully local, offline transcription -- audio never leaves your machine.
- Live "Me" / "Them" speaker bubbles as the call happens.
- Search, tag, and organize transcripts into folders.
- In-app update check against GitHub Releases.
- First-run onboarding message and recording-consent gate.
- Theme setting: System, Light, or Dark, applied before first paint to avoid a flash.
- Waiting indicator in the live view between speaker turns.
- Click-outside-to-close for dismissible modals (audio device picker, app settings).
