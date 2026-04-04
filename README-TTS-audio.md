# TTS Audio in Cross

Text-to-speech (TTS) is an **optional** feature that converts research reports into
spoken MP3 audio files.  Every other Cross command — report generation, fact-checking,
benchmarking, posting to Discourse — works without it.

When TTS is enabled, a story like this:

```bash
st-gen my_topic.json       # generate reports from 5 AI providers
st-prep my_topic.json      # process text
st-speak my_topic.json     # → my_topic.mp3  (spoken audio)
```

produces a broadcast-quality MP3 you can post to a podcast, YouTube, or social video.

---

## How it works

Cross does not bundle a speech engine.  It connects over a local network socket to a
**Wyoming Piper TTS server** — an open-source, locally-running neural TTS service.
The flow is:

```
Cross (st-speak / st-prep --mp3)
  │  TCP socket
  ▼
Piper TTS server (running locally or on your LAN)
  │  returns audio bytes
  ▼
MP3 file written to disk
```

The `yakyak` Python package handles the socket protocol.  `soundfile` writes the
audio frames to MP3.  Neither makes any internet requests at render time.

---

## Python version requirements

The table below is based on **live install + import tests on macOS ARM (Apple Silicon),
2026-03-31** — not inferred from wheel availability alone.
See `tests/test_tts_stack.py` to reproduce on any machine.

| Version | No-TTS | With TTS | numpy resolved |
|---------|--------|----------|----------------|
| 3.9     | ❌ | ❌ | numpy 2.2+ requires 3.10 — hard fail at `pip install` |
| 3.10    | ✅ | ✅ | 2.2.6 (numpy 2.3+ raised its floor to 3.11) |
| 3.11    | ✅ | ✅ | 2.2.4 (pinned in requirements.txt) |
| 3.12    | ✅ | ✅ | 2.4.4 — all 18 packages pass import test |
| 3.13    | ✅ | ✅ | 2.4.4 — all 18 packages pass import test |

**Minimum is Python 3.10** regardless of TTS, driven by:
- `numpy>=2.2` and `scipy>=1.15` dropped Python 3.9 wheels
- `match`/`case` syntax in `st-plot.py` and `st-voice.py` is Python 3.10+ only
- Python 3.9 is EOL (October 2025)

**There is no upper limit for TTS.** The claim that TTS requires Python 3.11 on
macOS ARM was incorrect and has been corrected throughout the codebase.

**numpy version resolution note:** numpy 2.3.x raised its `Requires-Python` to `>=3.11`.
On Python 3.10, `pip install "numpy>=2.2.4"` resolves to 2.2.x (the latest 3.10-compatible
branch) automatically — no manual pinning needed. On 3.11+ it resolves to 2.4.x.
All branches are fully compatible with Cross.

### Verified wheel tags (macOS ARM)

| Package | Wheel tag | Python versions |
|---------|-----------|-----------------|
| `soundfile 0.13.1` | `py2.py3-none-macosx_11_0_arm64` | Any — bundles libsndfile binary |
| `yakyak 1.7.0` | `py3-none-any` | 3.7 – 3.13 (pure Python) |
| `websockets 15.0.1` | `cp3XX-cp3XX-macosx_11_0_arm64` | Separate wheels for 3.9 – 3.13 |

---

## Platform support

| Platform | TTS supported | Notes |
|----------|---------------|-------|
| macOS ARM (Apple Silicon) | ✅ Full | `soundfile` bundles `libsndfile`; `afplay` for in-terminal playback |
| macOS Intel | ✅ Full | Same packages; Intel wheel used automatically |
| Linux x86_64 | ✅ Full | Install `libsndfile1` via package manager (see below) |
| Linux ARM64 (Pi, etc.) | ✅ Full | Same `libsndfile1` requirement |
| Windows (native) | ❌ Not supported | `soundfile` has no Windows wheel; `fcntl`/`termios` missing |
| Windows (WSL2) | ✅ Full | Ubuntu under WSL2 = full Linux support |

---

## Installation

### macOS (ARM or Intel)

```bash
# Recommended: pipx (isolated, no venv management)
pipx install "cross-st[tts]"

# Or inside a project venv:
pip install "cross-st[tts]"
# or from requirements.txt:
pip install -r requirements.txt
```

`soundfile` on macOS bundles its own `libsndfile` binary — no Homebrew package needed.

If you want the latest Python:

```bash
brew install python@3.12   # or @3.10, @3.11, @3.13 — all work
pipx install --python python3.12 cross-st
```

### Linux — Debian / Ubuntu

```bash
# 1. Install system audio library (required by soundfile on Linux)
sudo apt update
sudo apt install libsndfile1 ffmpeg

# 2. Python 3.10 or higher
sudo apt install python3.11 python3.11-venv   # or 3.10, 3.12, 3.13

# 3. Install Cross with TTS
pipx install "cross-st[tts]"
# or inside a venv:
pip install "cross-st[tts]"
```

> **Why `libsndfile1`?**  On Linux, `soundfile` uses a pure-Python wheel that
> expects `libsndfile` already installed on the system.  On macOS the library
> is bundled inside the wheel itself.

In-terminal voice playback (`s` key in `st-voice`) uses `afplay` on macOS.
On Linux, install a compatible player:

```bash
sudo apt install mpv         # recommended
# or: sox (provides 'play'), alsa-utils (provides 'aplay')
```

Then set `AUDIO_PLAYER=mpv` in `~/.crossenv` if Cross doesn't detect it automatically.

### Linux — Fedora / RHEL

```bash
sudo dnf install libsndfile ffmpeg python3.11
pipx install "cross-st[tts]"
```

### Linux — Arch

```bash
sudo pacman -S libsndfile ffmpeg python
pipx install cross-st
```

### Windows

Native Windows is not supported for TTS (no `soundfile` Windows wheel, and Cross
uses POSIX APIs for keyboard input and file locking).

**Use WSL2 (recommended):**

```powershell
# PowerShell — install WSL2 with Ubuntu
wsl --install
```

Then open the Ubuntu terminal and follow the Linux instructions above.

---

## Piper TTS server setup

TTS will not work until a Piper server is running.  Cross connects to it at render
time via `TTS_HOST` and `TTS_PORT`.

### Option A — Docker (easiest, any platform)

```bash
# Pull and start Wyoming Piper
docker run -d \
  --name wyoming-piper \
  -p 10200:10200 \
  -v /path/to/your/voices:/data \
  rhasspy/wyoming-piper \
  --voice en_US-lessac-medium
```

Replace `/path/to/your/voices` with a local directory where ONNX model files will live.

### Option B — Native (macOS / Linux)

Wyoming Piper can run natively if Docker is not available.  See the
[Wyoming Piper README](https://github.com/rhasspy/wyoming-piper) for installation.
The short form on macOS/Linux with `pipx`:

```bash
pipx install wyoming-piper
wyoming-piper --voice en_US-lessac-medium --uri tcp://0.0.0.0:10200
```

### Configure Cross to find the server

Add to `~/.crossenv` (or `.env`):

```env
TTS_HOST=localhost
TTS_PORT=10200
TTS_VOICE=en_US-lessac-medium
```

Or use `st-admin`:

```bash
st-admin --set-tts-voice en_US-lessac-medium
# TTS_HOST and TTS_PORT default to localhost:10200 when not set
```

---

## Voice management

Piper has hundreds of English voices.  Each voice requires an ONNX model file
downloaded from Hugging Face.

### Browse available voices

```bash
st-voice --voices        # lists all available en_US / en_GB voice names
```

### Download voice models

```bash
st-voice --curl          # prints curl commands for all voices
st-voice --curl | bash   # pipe to bash to download everything at once
```

Models are ONNX files (~30 MB – 130 MB each) downloaded from Hugging Face.
Store them in the directory your Piper server is configured to watch.

### Audition voices interactively

```bash
st-voice sample.txt      # opens an interactive shell
```

Interactive commands: `v` next voice · `s` speak · `e` edit text · `q` quit

### Set your default voice

```bash
st-admin --set-tts-voice en_US-lessac-medium   # CLI
st-admin                                        # or press V in interactive menu
```

Good starting voices: `en_US-lessac-medium`, `en_US-ryan-high`, `en_US-libritts-high`

---

## TTS commands

| Command | What it does |
|---------|-------------|
| `st-speak my_topic.json` | Render story 1 → `my_topic.mp3` |
| `st-speak -s 3 my_topic.json` | Render story 3 |
| `st-speak --source fact my_topic.json` | Read the fact-check report aloud |
| `st-speak --voice en_US-ryan-high my_topic.json` | Override voice for this render |
| `st-prep my_topic.json --mp3` | Render text + MP3 in one step |
| `st-prep my_topic.json --all` | Export md, mp3, txt, title all at once |
| `st-voice --voices` | List available voice names |
| `st-voice --curl \| bash` | Download all voice model files |
| `st-voice sample.txt` | Interactive voice audition shell |
| `st-admin --set-tts-voice VOICE` | Persist default voice to `~/.crossenv` |

---

## Without TTS

All commands except `st-speak`, `st-voice`, and `st-prep --mp3`/`--all` work
without TTS packages installed.

`pipx install cross-st` installs TTS by default (recommended for most users).

To install without TTS on a minimal system (CI, containers, Windows without WSL2):

```bash
# Option A — install from the source repo (developer/contributor installs)
pip install -r requirements-no-tts.txt

# Option B — install from PyPI and immediately uninstall the TTS packages
pip install cross-st
pip uninstall -y cmudict pyphen soundfile websockets wyoming yakyak
```

> **Why can't `pipx install "cross-st[no-tts]"` skip TTS?**
> Python extras can only *add* dependencies to a package, never remove them.
> Because TTS packages are part of `cross-st`'s core dependencies, no extras
> mechanism can exclude them in a single-package install.  The `[no-tts]` extra
> exists as a documentation signal — it installs the same full set as
> `pipx install cross-st`.  The uninstall workaround above is the supported
> path for genuinely TTS-free environments.

If you run a TTS command without the packages present, Cross exits cleanly:

```
Error: st-speak requires TTS packages.
Run: pipx install --force cross-st
```

To restore TTS to an existing install:

```bash
pipx install --force cross-st
```

---

## Troubleshooting

### `TTS host localhost:10200 is offline`

The Piper server is not running.  Start it with Docker or natively (see above),
then verify:

```bash
nc -z localhost 10200 && echo "server is up" || echo "server is down"
```

### `Error: soundfile not found` or `ImportError`

TTS packages are not installed:

```bash
pip install "cross-st[tts]"
```

### `libsndfile` error on Linux

```bash
sudo apt install libsndfile1    # Debian/Ubuntu
sudo dnf install libsndfile     # Fedora
sudo pacman -S libsndfile       # Arch
```

### Voice model not found by Piper

The ONNX model file is missing from the directory your server is watching.
Run `st-voice --curl | bash` to download all models, or download a specific one:

```bash
st-voice --curl | grep "lessac-medium" | bash
```

### No audio playback on Linux in `st-voice`

`afplay` is macOS-only.  Install `mpv` and add `AUDIO_PLAYER=mpv` to `~/.crossenv`:

```bash
sudo apt install mpv
echo "AUDIO_PLAYER=mpv" >> ~/.crossenv
```

---

## See also

- `st-voice --help` — voice management details
- `st-speak --help` — render options
- `st-admin --help` — settings management
- [Wyoming Piper](https://github.com/rhasspy/wyoming-piper) — TTS server
- [Piper voices](https://github.com/rhasspy/piper/blob/master/VOICES.md) — full voice list
- `README-TTS-audio.md` is the companion doc; the [Cross Wiki tts-audio page](https://github.com/b202i/cross-st/wiki/tts-audio) covers the same material in a browsable format

