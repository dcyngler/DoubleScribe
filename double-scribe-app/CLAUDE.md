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
  - **Authenticode signing (SmartScreen) — not yet set up, see "Cutting a release" below for the
    plan.** Until it is, first-time browser downloaders will see a SmartScreen "Windows protected
    your PC" interstitial.

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
the user ends up back in the app on the new version with no dialogs at all. There's also an
in-app "What's new" modal, driven by `app/release_notes.py`, shown once per version bump —
separate from the update check, just local content bundled at build time.

**Signature verification (parity with Handy's minisign check):** every installer is signed
with an Ed25519 key before it's attached to the release. `app/api.py` embeds the **public**
half as `UPDATE_PUBKEY_B64`; `update-signing-key.pem` (repo root, gitignored, generated once by
`scripts/generate_update_key.py`) holds the **private** half and must never be committed or
leave this machine / your secure backup. `install_update()` requires a same-named `<exe>.sig`
asset on the release — if it's missing, or the signature doesn't verify against
`UPDATE_PUBKEY_B64`, the installer is deleted **without being run** and the UI falls back to the
release-page link, same as if there were no asset at all. This means an unsigned or tampered
release, or one still mid-upload, can never be silently auto-installed.

**Authenticode signing (SmartScreen), copied from Handy's approach:** Handy
(github.com/cjpais/Handy, the project this app's update flow is modeled on) signs its Windows
builds with **Azure Trusted Signing** via the `trusted-signing-cli` / `artifact-signing-cli` tool
(github.com/Levminer/trusted-signing-cli — renamed `artifact-signing-cli` as of v0.11.0; ships
pre-built Windows binaries, no Rust toolchain needed), invoked as:
```
artifact-signing-cli -e <endpoint> -a <account-name> -c <cert-profile-name> -d "Double Scribe" installer\DoubleScribeSetup.exe
```
authenticated via an Azure service principal (`AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`,
`AZURE_TENANT_ID` env vars). This is the same technique referenced in Handy's `tauri.conf.json`:
`trusted-signing-cli -e https://eus.codesigning.azure.net/ -a CJ-Signing -c cjpais-dev -d Handy %1`.

**Not set up yet for this project** — requires, one-time, outside this repo:
1. An Azure subscription and a **Trusted Signing Account** + **Certificate Profile** (Public Trust
   type) created in the Azure Portal. For an individual (not a registered business), this needs
   identity verification through Microsoft's process (government ID, can take a few days).
   Cost is per Azure's current Trusted Signing pricing (Basic tier, billed monthly).
2. An Entra ID App Registration (service principal) granted the "Trusted Signing Certificate
   Profile Signer" role on that account — its client ID / secret / tenant ID become
   `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` / `AZURE_TENANT_ID`.

**Critical ordering once this exists:** Authenticode-sign the compiled installer **before** the
Ed25519 step (`scripts/sign_release.py`), not after — Authenticode signing embeds a signature
into the PE file itself (changes its bytes), so the Ed25519 signature must be computed over the
*final* signed file, or it won't verify. Insert the Authenticode step between checklist steps 3
and 4 below.

Checklist, in order:
1. Bump the version in **two places** (they must match — nothing enforces this automatically):
   `APP_VERSION` in `app/api.py` and `MyAppVersion` in `DoubleScribe.iss`.
2. Add an entry to `CHANGELOG.md` (full log) **and** a short bullet list for the same version key
   in `app/release_notes.py` (terser — this is what actually renders in the in-app modal).
3. Build: `.venv\Scripts\pyinstaller.exe DoubleScribe.spec --noconfirm`, then
   `"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" DoubleScribe.iss` → `installer\DoubleScribeSetup.exe`.
3a. **(Once Azure Trusted Signing is set up — currently skipped)** Authenticode-sign:
    `artifact-signing-cli -e <endpoint> -a <account> -c <profile> -d "Double Scribe" installer\DoubleScribeSetup.exe`.
4. Sign it: `.venv\Scripts\python.exe scripts\sign_release.py installer\DoubleScribeSetup.exe`
   → writes `installer\DoubleScribeSetup.exe.sig` next to it. Must run **after** step 3a if that
   step was performed (see ordering note above).
5. `git tag vX.Y.Z && git push origin vX.Y.Z`.
6. `gh release create vX.Y.Z installer\DoubleScribeSetup.exe installer\DoubleScribeSetup.exe.sig --title "vX.Y.Z" --notes-file <changelog section for this version>`
   — **both files must be attached** (exe *and* .sig) for the in-app updater to auto-install;
   a release missing either just makes clients fall back to the release-page link.

The update check and "What's new" modal both read `APP_VERSION`/`NOTES` bundled at build time —
there's no way for an already-installed copy to see release notes for a version newer than the
one it's running, by design (it'll just self-update to that version and see the modal next launch).
