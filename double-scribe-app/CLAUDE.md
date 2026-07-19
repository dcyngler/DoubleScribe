# Double Scribe — project guide (read me first)

This file lets a fresh Claude Code session (or another engineer) pick up and update this
app without re-learning it. Read this, then the file you need to change.

## What this is
A fully-local, offline audio transcriber for Windows. Captures the computer's audio output
("Them" — the call) and the microphone ("Me"), transcribes with Whisper, saves `.txt`
transcripts. Nothing is uploaded. There are **three** front-ends over one engine:

| Launcher | File | What it is |
|---|---|---|
| `Run.bat` | `transcriber.py` | Original Tkinter app — record, then transcribe at the end (has speaker diarisation) |
| `Run_Live.bat` | `live_transcriber.py` | Tkinter live app — transcribes as you speak |
| `Run_App.bat` / **"Double Scribe"** shortcut | `app/` | **The main app** — polished pywebview UI |

Most work now happens in **`app/`** (the new UI). The two Tkinter files are the working
engine and must keep working — treat them as stable; the new UI reuses them.

## Environment (important — bleeding edge)
- **Python 3.14** in `.venv` (`.venv\Scripts\python.exe`, `pythonw.exe` for no-console).
- Key deps: `faster-whisper` (+`ctranslate2`), `soundcard`, `sherpa-onnx` (speaker embeddings —
  full diarisation in the Tkinter apps, lightweight "Them" voice-change split in the new UI),
  `pywebview`(+`pythonnet`), `numpy`, `pillow`, `pywin32`.
- GPU: `nvidia-*-cu12` wheels present (~1.9 GB) → Whisper runs on the RTX Blackwell GPU,
  falls back to CPU automatically. `transcriber._add_nvidia_dll_dirs()` puts the CUDA DLLs
  on PATH (CTranslate2 needs PATH, not just add_dll_directory).
- Models: Whisper "small" cached in `~/.cache/huggingface`; sherpa ONNX models in `models/`.
- Run any script with `.venv\Scripts\python.exe`, never the system Python.

## New UI architecture (`app/`)
- `engine.py` — headless controller. **Reuses** `live_transcriber.LiveChannel`,
  `transcribe_utterance`, `END_SILENCE_*`, and `transcriber.load_model`. Its own local
  `_group_turns()` (not `transcriber.group_turns`) merges consecutive same-label phrases,
  same as before, but a `voice_change`-flagged "Them" phrase always starts a new turn.
  `start(out_index=-1, in_index=-1)` → **-1 = Auto: capture ALL outputs + ALL mics**; silent
  devices produce nothing, active one transcribes; a dedupe window drops duplicate phrases.
  Labels are only **Me** (mic) / **Them** (speakers) — no naming/identity across the call.
  `load_speaker_model()` loads `live.VoiceChangeDetector` (needs `sherpa-onnx` +
  `models/nemo_en_titanet_small.onnx` — see gotchas); each "Them" phrase is embedded and
  cosine-compared only to the *previous* "Them" phrase, so a different remote voice gets its
  own bubble without ever naming/re-recognising speakers. If the model/package is missing,
  `voice_detector` stays `None` and it silently falls back to one merged "Them" bubble.
- `store.py` — owns `index.json` (metadata: title/tags/folders/favourite/preview). Auto-imports
  existing `transcripts/*.txt`. `get_transcript()` returns `{meta, body, messages}` where
  `messages` = `[{who:'me'|'them', text}]` for chat bubbles. `_collapse_speakers()` maps any
  old `Speaker N` → `Them` **for display only** (never rewrites files).
- `api.py` — pywebview bridge (methods called from JS as `window.pywebview.api.*`) + pushes
  live events to JS via `window.evaluate_js`.
- `app.py` — bootstrap. Sets `SetCurrentProcessExplicitAppUserModelID("Bevington.DoubleScribe")`
  so the taskbar shows our name/icon; `webview.start(icon="app/icon.ico")` (WebView2 needs `.ico`).
- `web/index.html`, `web/styles.css`, `web/app.js` — the frontend (sidebar/list/detail + live
  view). Transcript shows as **chat bubbles**: Me = right, brand blue `#0033CC`; Them = left,
  grey `#F0F0F2`; no inline labels.

## Data & conventions
- Transcripts: `transcripts/live-YYYYMMDD-HHMMSS.txt`, still written **with `Me:`/`Them:` labels**
  (so Copy all / Export keep them). Titles live only in `index.json`, never in filenames.
- **Never delete files** (org policy). The UI "Delete" is **archive** (`archived:true` in
  index.json) — hides it, keeps the `.txt`. Only ever offer the user a path to delete themselves.
- Brand blue is `#0033CC`. App icon: `app/icon.ico` / `app/icon.png` (blue tile + white mic).

## Common updates — where to look
- Live sensitivity / phrase splitting: `live_transcriber.py` top constants
  (`END_SILENCE_ME/THEM`, `MIN_RMS`, `SPEECH_MULT`, `PREROLL`).
- UI look: `app/web/styles.css`. UI behaviour: `app/web/app.js`. Bridge methods: `app/api.py`.
- Whisper model size / device: `transcriber.py` `MODEL_SIZE`, `load_model()`.

## How to verify a change (no real audio needed)
Backend: `cd app && ..\.venv\Scripts\python.exe -c "import store; s=store.Store(); s.auto_import(); print(len(s.list()['transcripts']))"`.
UI: launch pywebview with the real `app/web` and a background thread that `evaluate_js`
inspects the DOM then `win.destroy()` — see the `scratchpad/verify_*.py` pattern used during
the build (open a `.card`, count `.bubble`, check computed styles). Print ASCII only (the
Windows console is cp1252 — emoji/✓ crash `print`).

## Known gotchas
- Python 3.14 is new: check wheels exist before adding deps (`pip install --dry-run <pkg>`).
- `models/` is gitignored (see `.gitignore`), so on a fresh clone `sherpa-onnx` is installed
  but `models/nemo_en_titanet_small.onnx` doesn't exist — the new UI's "Them" voice-change
  split (and the Tkinter apps' diarisation) silently no-op until it's fetched:
  `curl -L -o models/nemo_en_titanet_small.onnx https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/nemo_en_titanet_small.onnx`.
  `DoubleScribe.spec` now bundles `sherpa_onnx` + this model (it's only ~38MB, so unlike
  Whisper it's bundled at build time, not downloaded) *if* it's present on the build machine
  when you run PyInstaller — verified working end-to-end via `DS_SMOKE=1` (`voice_split=True`
  in `smoke.txt`). If the file is missing at build time, the spec just skips it and the
  installed .exe falls back to one merged "Them" bubble, same as running from source without it.
- Fresh-process GPU start is slow (~4–10 s cold cuDNN); Whisper "ready" then usable.
- Setting a shortcut's AppUserModelID: use `propsys.SHGetPropertyStoreFromParsingName(path, None, 2, IID_IPropertyStore)` — the `IPersistFile.Save` route returned Access Denied.
- Distribution (done): CPU-only. Whisper "small" is **not** bundled — it downloads on first run
  (see below) to keep the installer small. Two build files at repo root:
  - `DoubleScribe.spec` — PyInstaller onedir. Excludes the NVIDIA CUDA wheels; bundles `app/web`,
    the icon, `sherpa_onnx`, and the voice-change model (no Whisper model — see above).
    Build: `.venv\Scripts\pyinstaller.exe DoubleScribe.spec --noconfirm` → `dist\DoubleScribe\`.
  - `DoubleScribe.iss` — Inno Setup, per-user (no admin). Compile with
    `"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" DoubleScribe.iss` → `installer\DoubleScribeSetup.exe`.
  - Packaging-aware paths live in `transcriber.py`: `RESOURCE_DIR` (=`sys._MEIPASS` when frozen),
    `DATA_DIR` (=`%LOCALAPPDATA%\DoubleScribe` when frozen — transcripts + index.json go here,
    never in the install dir), `MODEL_DIR` (=`DATA_DIR/models/whisper-small`, downloaded by
    `ensure_model()` on first run via `faster_whisper.download_model`, then reused offline every
    run after), and `load_model` forces CPU/int8 when frozen.
  - Verify a build headlessly: `set DS_SMOKE=1 && DoubleScribe.exe` downloads the model if needed,
    loads it on CPU, and writes `ready=…/status=…` to `%LOCALAPPDATA%\DoubleScribe\smoke.txt`
    (the hook is in `app/app.py`) — the first smoke run needs internet access.
  - Unsigned exe may be flagged by corporate AV; WebView2 is needed on target (ships with Windows 11).

## Cutting a release
The repo is public and the app checks `https://api.github.com/repos/dcyngler/DoubleScribe/releases/latest`
on every launch (`app/api.py` `_check_for_update`, gated by the `update_checks_enabled` setting —
a toggle in App settings, default on) to show an "Update available" link in the status bar.
Clicking it is a **silent self-update**, Handy-style: `install_update()` downloads the first
`.exe` asset on the release to `%TEMP%`, reports progress via `onUpdateProgress`, then launches
it with `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART` and quits (`_window.destroy()` + `os._exit`).
Because the install is per-user (`PrivilegesRequired=lowest`), there's no UAC prompt. Inno's
`CloseApplications`/`RestartApplications` (`DoubleScribe.iss`) handle the running exe/DLL locks,
and a `skipifnotsilent` `[Run]` entry relaunches the app once the silent install finishes — so
the user ends up back in the app on the new version with no dialogs at all. If a release has no
`.exe` asset yet (upload still in progress), it falls back to opening the release page instead.
There's also an in-app "What's new" modal, driven by `app/release_notes.py`, shown once per
version bump — separate from the update check, just local content bundled at build time.

**Caveat vs. Handy:** Handy's Tauri updater verifies a minisign signature on the downloaded
artifact before installing. This flow has no equivalent signature check — it trusts the HTTPS
connection to GitHub's release asset host, same trust boundary as the old manual-download link.
Worth adding (e.g. a published SHA-256 checksum, or real code signing) before relying on this
for anything more sensitive than what's already true today.

Checklist, in order:
1. Bump the version in **two places** (they must match — nothing enforces this automatically):
   `APP_VERSION` in `app/api.py` and `MyAppVersion` in `DoubleScribe.iss`.
2. Add an entry to `CHANGELOG.md` (full log) **and** a short bullet list for the same version key
   in `app/release_notes.py` (terser — this is what actually renders in the in-app modal).
3. Build: `.venv\Scripts\pyinstaller.exe DoubleScribe.spec --noconfirm`, then
   `"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" DoubleScribe.iss` → `installer\DoubleScribeSetup.exe`.
4. `git tag vX.Y.Z && git push origin vX.Y.Z`.
5. `gh release create vX.Y.Z installer\DoubleScribeSetup.exe --title "vX.Y.Z" --notes-file <changelog section for this version>`
   — the `.exe` **must** be attached to the release for the in-app updater to find it (that's
   what this command does); a tag/release with no asset just makes clients fall back to the
   release-page link.

The update check and "What's new" modal both read `APP_VERSION`/`NOTES` bundled at build time —
there's no way for an already-installed copy to see release notes for a version newer than the
one it's running, by design (it'll just self-update to that version and see the modal next launch).
