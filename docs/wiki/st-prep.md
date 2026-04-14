# st-prep — Prepare a raw AI response into a publishable story

Converts a raw AI response into a clean, structured story and appends it to the container. Extracts the title and hashtags, and optionally renders an MP3 audio file.

**Run after:** `st-gen` · `st-fetch`  ·  **Run before:** `st-fact` · `st-post`

## Examples

```bash
st-prep subject.json              # process data entry 1, add story to container
st-prep -d 2 subject.json         # process data entry 2
st-prep -d 1 --mp3 subject.json   # also render an MP3 audio file
st-prep -d 1 --all subject.json   # export md, mp3, title, and txt files
```

**Options:** `-d`  `data`  `-a`  `all`  `--markdown`  `--mp3`  `--title`  `--txt`  `--bang`  `-v`  `-q`

**Related:** [st-gen](st-gen) · [st-fact](st-fact) · [st-speak](st-speak)

---

## For developers

Called automatically by `st-gen --prep`, `st-cross`, `st-fetch`, and `st-fix`. Writes to `story[]` in the container. TTS rendering (`--mp3`) uses `mmd_voice.py` and requires the TTS extras (`pip install 'cross-ai[tts]'`).
