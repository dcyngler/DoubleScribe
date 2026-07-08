# Live Transcriber — project guide (read me first)

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
| `Run_App.bat` / **"Live Transcriber"** shortcut | `app/` | **The main app** — polished pywebview UI (legacy-tool-style) |

Most work now happens in **`app/`** (the new UI). The two Tkinter files are the working
engine and must keep working — treat them as stable; the new UI reuses them.

## Environment (important — bleeding edge)
- **Python 3.14** in `.venv` (`.venv\Scripts\python.exe`, `pythonw.exe` for no-console).
- Key deps: `faster-whisper` (+`ctranslate2`), `soundcard`, `sherpa-onnx` (installed but the
  new UI no longer uses it), `pywebview`(+`pythonnet`), `numpy`, `pillow`, `pywin32`.
- GPU: `nvidia-*-cu12` wheels present (~1.9 GB) → Whisper runs on the RTX Blackwell GPU,
  falls back to CPU automatically. `transcriber._add_nvidia_dll_dirs()` puts the CUDA DLLs
  on PATH (CTranslate2 needs PATH, not just add_dll_directory).
- Models: Whisper "small" cached in `~/.cache/huggingface`; sherpa ONNX models in `models/`.
- Run any script with `.venv\Scripts\python.exe`, never the system Python.

## New UI architecture (`app/`)
- `engine.py` — headless controller. **Reuses** `live_transcriber.LiveChannel`,
  `transcribe_utterance`, `END_SILENCE_*`, and `transcriber.load_model` / `group_turns`.
  `start(out_index=-1, in_index=-1)` → **-1 = Auto: capture ALL outputs + ALL mics**; silent
  devices produce nothing, active one transcribes; a dedupe window drops duplicate phrases.
  Labels are only **Me** (mic) / **Them** (speakers) — per-speaker matching is OFF.
- `store.py` — owns `index.json` (metadata: title/tags/folders/favourite/preview). Auto-imports
  existing `transcripts/*.txt`. `get_transcript()` returns `{meta, body, messages}` where
  `messages` = `[{who:'me'|'them', text}]` for chat bubbles. `_collapse_speakers()` maps any
  old `Speaker N` → `Them` **for display only** (never rewrites files).
- `api.py` — pywebview bridge (methods called from JS as `window.pywebview.api.*`) + pushes
  live events to JS via `window.evaluate_js`.
- `app.py` — bootstrap. Sets `SetCurrentProcessExplicitAppUserModelID("Bevington.LiveTranscriber")`
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
- Fresh-process GPU start is slow (~4–10 s cold cuDNN); Whisper "ready" then usable.
- Setting a shortcut's AppUserModelID: use `propsys.SHGetPropertyStoreFromParsingName(path, None, 2, IID_IPropertyStore)` — the `IPersistFile.Save` route returned Access Denied.
- Distribution (done): CPU-only, offline, Whisper "small" bundled. Two build files at repo root:
  - `LiveTranscriber.spec` — PyInstaller onedir. Excludes the NVIDIA CUDA wheels and `sherpa_onnx`;
    bundles `app/web`, the icon, and the model staged in `build_assets/whisper-small/`.
    Build: `.venv\Scripts\pyinstaller.exe LiveTranscriber.spec --noconfirm` → `dist\LiveTranscriber\`.
  - `LiveTranscriber.iss` — Inno Setup, per-user (no admin). Compile with
    `"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" LiveTranscriber.iss` → `installer\LiveTranscriberSetup.exe`.
  - Packaging-aware paths live in `transcriber.py`: `RESOURCE_DIR` (=`sys._MEIPASS` when frozen),
    `DATA_DIR` (=`%LOCALAPPDATA%\LiveTranscriber` when frozen — transcripts + index.json go here,
    never in the install dir), `BUNDLED_WHISPER`, and `load_model` forces CPU/int8 when frozen.
  - Verify a build headlessly: `set LT_SMOKE=1 && LiveTranscriber.exe` loads the model on CPU and
    writes `ready=…/status=…` to `%LOCALAPPDATA%\LiveTranscriber\smoke.txt` (the hook is in `app/app.py`).
  - Unsigned exe may be flagged by corporate AV; WebView2 is needed on target (ships with Windows 11).
