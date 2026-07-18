# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Double Scribe (CPU-only, offline once the model is downloaded).

Build:  .venv\Scripts\pyinstaller.exe DoubleScribe.spec --noconfirm
Output: dist\DoubleScribe\DoubleScribe.exe  (onedir)

Notes
- CPU-only: the NVIDIA CUDA wheels are NOT collected (see excludes). transcriber.load_model
  runs CPU/int8 when frozen, so no GPU libraries are needed on the target machine.
- Model is NOT bundled: the Whisper 'small' model is downloaded on first run into
  %LOCALAPPDATA%\DoubleScribe\models (see transcriber.ensure_model), keeping the installer
  small. Every run after the first is fully offline again.
- The "Them" voice-change split (app/engine.py's VoiceChangeDetector) needs sherpa_onnx +
  models/nemo_en_titanet_small.onnx. Unlike Whisper, this model is small (~38MB) so it IS
  bundled at build time -- no first-run download for it. If models/nemo_en_titanet_small.onnx
  hasn't been fetched on the build machine (see CLAUDE.md), it's simply left out and the
  feature no-ops at runtime exactly as it does today when the file is missing.
- The two Tkinter engine modules (transcriber.py, live_transcriber.py) live one level up from
  app/, so pathex includes the repo root and app/ for the analysis to find them.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

datas = [
    ('app/web', 'web'),               # HTML/CSS/JS frontend
    ('app/icon.ico', '.'),            # window / taskbar icon (WebView2 needs .ico)
    ('app/icon.png', '.'),
]
binaries = []
hiddenimports = [
    'tokenizers', 'huggingface_hub', 'av',
    'transcriber', 'live_transcriber',   # sibling engine modules (loaded via sys.path)
    'api', 'engine', 'store',
]

# Voice-embedding model for the "Them" voice-change split -- optional, bundled only if the
# developer has already fetched it (see CLAUDE.md gotchas); silently skipped otherwise.
_voice_model = Path('models/nemo_en_titanet_small.onnx')
if _voice_model.exists():
    datas.append((str(_voice_model), 'models'))
else:
    print(f"[spec] {_voice_model} not found -- voice-change split will be disabled in this build")

# Packages with data files / native DLLs that PyInstaller can't fully trace statically.
# pywebview pulls in the WebView2 + WinForms host DLLs; pythonnet ships Python.Runtime.dll;
# sherpa_onnx ships a compiled extension module for the voice-change split.
for pkg in ('faster_whisper', 'ctranslate2', 'soundcard', 'webview',
            'clr_loader', 'pythonnet', 'cffi', 'sherpa_onnx'):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:   # noqa: BLE001 -- surfaced in the build log, non-fatal
        print(f"[spec] collect_all({pkg!r}) skipped: {exc}")

a = Analysis(
    ['app/app.py'],
    pathex=['.', 'app'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'nvidia',             # CPU-only build: no CUDA wheels
        'torch', 'tensorflow', 'jax',
        'matplotlib', 'pandas', 'scipy',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'wx',   # other pywebview GUI backends
        'pytest', 'IPython',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DoubleScribe',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                 # windowed app, no console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app/icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='DoubleScribe',
)
