# Local Transcriber

A small, fully-offline tool that listens to your **computer's audio output**
(what you hear) and your **microphone** (what you say), and turns it into a text
transcript. You toggle it on and off whenever you like.

- **Nothing is uploaded.** Transcription runs locally with Whisper.
- **No recordings are kept.** Audio is held in memory only while you're
  recording, then discarded once it's been transcribed. Only the text remains.
- Each line is labelled **Me** (your mic) or **Them** (your speakers), so you
  get a free speaker hint without any extra setup.

## Running it

Double-click **`run.bat`**, or from a terminal:

```
.venv\Scripts\python.exe transcriber.py
```

1. Wait for the status to say **Ready** (first launch downloads the Whisper
   model once, ~460 MB).
2. Click **● Start** to begin listening.
3. Click **■ Stop** when you're done — the transcript appears in the window.
4. If `SAVE_TRANSCRIPTS` is on, a `.txt` copy lands in `transcripts\`.

## Settings

Open `transcriber.py` and edit the block near the top:

| Setting | Default | What it does |
|---|---|---|
| `MODEL_SIZE` | `"small"` | Accuracy vs speed: `tiny` < `base` < `small` < `medium` < `large-v3` |
| `SAVE_TRANSCRIPTS` | `True` | Save each transcript to a `.txt` file |
| `KEEP_AUDIO` | `False` | Leave off — audio is never written to disk |

## Notes

- **Confidentiality:** because everything runs locally, audio never leaves this
  machine. The transcript `.txt` files are the only thing saved, in the
  `transcripts\` folder — manage or remove those yourself as needed.
- **GPU:** the tool uses your NVIDIA GPU automatically if the CUDA libraries are
  available, otherwise it falls back to the CPU (still works, just slower).
- **Per-person speaker labels** (Person A / B / C *within* the call, beyond
  Me/Them) are a possible future add-on using `pyannote.audio`. Not included yet.
