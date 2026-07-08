# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Live Transcriber (CPU-only, offline, Whisper 'small' bundled).

Build:  .venv\Scripts\pyinstaller.exe LiveTranscriber.spec --noconfirm
Output: dist\LiveTranscriber\LiveTranscriber.exe  (onedir)

Notes
- CPU-only: the NVIDIA CUDA wheels are NOT collected (see excludes). transcriber.load_model
  runs CPU/int8 when frozen, so no GPU libraries are needed on the target machine.
- Offline: the Whisper 'small' model is staged in build_assets/whisper-small and bundled to
  <app>/whisper-small; transcriber.BUNDLED_WHISPER loads it directly (no HuggingFace download).
- The two Tkinter engine modules (transcriber.py, live_transcriber.py) live one level up from
  app/, so pathex includes the repo root and app/ for the analysis to find them.
"""

from PyInstaller.utils.hooks import collect_all

datas = [
    ('app/web', 'web'),               # HTML/CSS/JS frontend
    ('app/icon.ico', '.'),            # window / taskbar icon (WebView2 needs .ico)
    ('app/icon.png', '.'),
    ('build_assets/whisper-small', 'whisper-small'),   # offline Whisper model
]
binaries = []
hiddenimports = [
    'tokenizers', 'huggingface_hub', 'av',
    'transcriber', 'live_transcriber',   # sibling engine modules (loaded via sys.path)
    'api', 'engine', 'store',
]

# Packages with data files / native DLLs that PyInstaller can't fully trace statically.
# pywebview pulls in the WebView2 + WinForms host DLLs; pythonnet ships Python.Runtime.dll.
for pkg in ('faster_whisper', 'ctranslate2', 'soundcard', 'webview',
            'clr_loader', 'pythonnet', 'cffi'):
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
        'sherpa_onnx',        # diarisation not used by the new UI; imported lazily only
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
    name='LiveTranscriber',
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
    name='LiveTranscriber',
)
