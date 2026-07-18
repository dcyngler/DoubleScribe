"""
Double Scribe -- desktop UI bootstrap.

Renders the HTML/CSS/JS frontend in a native window (pywebview / WebView2) and
wires it to the existing transcription engine via the Api bridge. Launched with
pythonw.exe, so there is no console window; it spawns no child processes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import os

import webview
from api import Api

HERE = Path(__file__).resolve().parent
INDEX_HTML = HERE / "web" / "index.html"
ICON = HERE / "icon.ico"   # WebView2 needs a Windows .ico for the window icon


def _smoke_test():
    """Headless self-test for the packaged build (set DS_SMOKE=1).

    Runs the normal boot path with no window -- downloads the model if needed,
    loads Whisper on CPU, and initialises the store -- then writes the outcome
    to <DATA_DIR>/smoke.txt and exits 0 on success, 2 on failure. Inert in
    normal use; lets a build be verified without a console or real audio.
    """
    import transcriber as core
    api = Api()
    api.boot()                      # _window is None -> UI pushes are no-ops
    voice_split = api.engine.voice_detector is not None
    result = (f"ready={api._ready}\nstatus={api._status}\nmodel={core.MODEL_DIR}\n"
              f"voice_split={voice_split}\n")
    try:
        (core.DATA_DIR / "smoke.txt").write_text(result, encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(0 if api._ready else 2)


def main():
    if os.environ.get("DS_SMOKE") == "1":
        _smoke_test()
        return

    # Give the app its own Windows identity so the taskbar uses OUR icon
    # instead of grouping under pythonw.exe and showing the generic Python icon.
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Bevington.DoubleScribe")
    except Exception:
        pass

    api = Api()
    window = webview.create_window(
        "Double Scribe",
        str(INDEX_HTML),
        js_api=api,
        width=1200,
        height=780,
        min_size=(940, 620),
        background_color="#FFFFFF",
    )
    api.attach(window)
    try:
        webview.start(api.boot, icon=str(ICON))   # sets window / taskbar icon
    except TypeError:
        webview.start(api.boot)                    # older pywebview without icon arg


if __name__ == "__main__":
    main()
