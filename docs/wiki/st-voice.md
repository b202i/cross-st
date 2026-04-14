# st-voice — Browse, download, and test Piper TTS voice models

Lists available TTS voices, prints download commands, and sets the active voice used by `st-speak`. The selected voice is saved to `TTS_VOICE` in your config.

**Related:** [st-speak](st-speak)  [st-admin](st-admin)  [TTS Audio](tts-audio)

---

## Examples

```bash
st-voice --voices                   # list all available .onnx voice models
st-voice --curl                     # print curl commands to download all voices
st-voice file.txt                   # test-render a text file with the current voice
st-voice -k                         # kill the Piper TTS server on port 6419
```

## Options

| Option | Description |
|--------|-------------|
| `file.txt` | Optional path to a text file to test-render with the current voice |
| `--voices` | Print names of all available Piper (.onnx) voice models |
| `--curl` | Print curl commands to download all Piper voice models |
| `-k`, `--kill` | Kill the Piper TTS server running on port 6419 |
| `-v`, `--verbose` | Verbose output |
| `-q`, `--quiet` | Minimal output |

---

## For developers

Voice models (`.onnx` files) are discovered from the local Piper TTS server. Run `st-admin` to set `TTS_HOST` and `TTS_PORT` if the server is not on `localhost:5000`. Voice files live in `~/.cross_voices/`; download them with the `--curl` output or set `TTS_VOICE` in `~/.crossenv`.
