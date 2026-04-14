# st-speak — Render a story into spoken audio (MP3)

Renders a story as an MP3 audio file using text-to-speech. Requires the TTS extras to be installed.

**Run after:** `st-prep`  ·  **Run before:** `st-post`

## Examples

```bash
st-speak subject.json               # render story 1 → subject.mp3
st-speak -s 3 subject.json          # render story 3
st-speak --source fact subject.json # read the fact-check report aloud
st-speak --voice en_US-ryan-high subject.json  # override voice for this render
```

**Options:** `-s`  `story`  `--source`  `{text,fact}`  `--voice`  `model`  `-v`  `-q`

**Related:** [st-voice](st-voice) · [st-post](st-post) · [TTS Audio](tts-audio)

---

## For developers

Requires `pip install 'cross-ai[tts]'`. Uses `mmd_voice.py` which connects to a local Piper TTS server (`TTS_HOST`/`TTS_PORT` in `.env`). Exits cleanly with an error message if TTS dependencies are missing.
