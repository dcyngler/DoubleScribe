# Changelog

All notable changes to Double Scribe are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/).

When you cut a release, add an entry here **and** a matching short bullet
list in `app/release_notes.py` (that one drives the in-app "What's new"
modal; this file is the full human-readable log).

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
