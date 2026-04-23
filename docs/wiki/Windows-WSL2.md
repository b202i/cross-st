# Windows / WSL2 — Installing Cross

Cross runs on Windows via **WSL2** (Windows Subsystem for Linux 2). This page walks you through a complete setup from a fresh Windows 11 machine to running your first report.

> **Tested on:** Windows 11 23H2 · Ubuntu 22.04 (WSL2) · Python 3.12

---

## 1. Enable WSL2

Open **PowerShell as Administrator** and run:

```powershell
wsl --install
```

This installs WSL2 and the default Ubuntu distribution in one step. Reboot when prompted.

> If you already have WSL1, upgrade to WSL2:
> ```powershell
> wsl --set-default-version 2
> ```

After reboot, open the **Ubuntu** app from the Start menu. The first launch asks you to create a UNIX username and password — these are independent of your Windows credentials.

---

## 2. Update Ubuntu and install Python tools

Inside your WSL2 terminal:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv pipx
```

Add pipx to your PATH and reload the shell:

```bash
pipx ensurepath
exec bash
```

---

## 3. Install Cross

```bash
pipx install "cross-st[tts]"
```

To install without TTS (`st-speak` / `st-voice` unavailable):

```bash
pipx install cross-st
```

If pipx says it's already installed, add `--force`:

```bash
pipx install --force cross-st
```

Reload your shell to pick up the new entry points:

```bash
exec bash
```

Verify all entry points are on PATH:

```bash
st --version
st-admin --version
```

---

## 4. Get an API key

You need at least one API key. **Start with Gemini — it's free.**

### ⭐ Google Gemini — Free tier (recommended for new users)

1. Go to [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Click **Create API key**
3. Copy the key — it starts with `AIza...`

Free tier: 15 requests/minute · 1,500 requests/day · 1M tokens/day.

---

## 5. Configure Cross

Run the setup wizard:

```bash
st-admin --setup
```

The wizard prompts for API keys, sets your default provider, and writes everything to `~/.crossenv` (that's `~` inside WSL2, not on your Windows drive).

Or configure manually:

```bash
st-admin --set DEFAULT_AI gemini
st-admin --set GEMINI_API_KEY AIza...
```

---

## 6. Run your first report

```bash
mkdir ~/my_reports && cd ~/my_reports
st-new                        # opens nano/vim — describe your topic, save & exit
st-bang                       # generate reports from all configured AIs in parallel
st-cross report.json          # cross-check every report against every other AI
st-heatmap report.json        # visualise the fact-check score matrix
```

---

## 7. Working with files on the Windows side

WSL2 can read and write Windows files via `/mnt/c/`:

```bash
cd /mnt/c/Users/<YourWindowsUsername>/Documents
mkdir cross_reports && cd cross_reports
```

Or from Windows Explorer, navigate to `\\wsl$\Ubuntu\home\<youruser>\` to see your WSL home directory.

> **Performance tip:** File I/O is significantly faster when your report files live inside WSL2's own filesystem (`~/`) rather than on `/mnt/c/`. For heavy workloads (hundreds of cross-checks), keep files in `~/`.

---

## 8. Editor integration

### VS Code with the WSL extension

1. Install [VS Code](https://code.visualstudio.com/) on Windows.
2. Install the **WSL** extension (id: `ms-vscode-remote.remote-wsl`).
3. From your WSL terminal:
   ```bash
   code .
   ```
   VS Code opens in Windows but runs all tools (Python, linters, `st-*`) inside WSL2.

### nano / vim (no install needed)

The default editor used by `st-new` is whatever `$EDITOR` is set to in your shell. Ubuntu 22.04 ships with `nano`:

```bash
export EDITOR=nano   # add to ~/.bashrc to persist
```

---

## 9. Optional: st-print PDF output

`st-print` uses WeasyPrint to generate PDFs, which requires native Pango/GObject libraries:

```bash
sudo apt install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b \
                    libfontconfig1 libcairo2 libgdk-pixbuf-2.0-0 \
                    libxml2 libssl-dev
pip install weasyprint
```

Then:

```bash
st-print report.json -o report.pdf
```

---

## 10. Troubleshooting

### `st` or `st-admin` not found after install

```bash
pipx ensurepath
exec bash
```

Then check:

```bash
echo $PATH | tr ':' '\n' | grep local
```

You should see `~/.local/bin` listed. If not, add it manually:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
exec bash
```

---

### `st-admin --setup` says no config found

You haven't run the setup wizard yet. Run it now:

```bash
st-admin --setup
```

---

### API key is set but `st-gen` fails with auth error

Check that `~/.crossenv` contains your key:

```bash
grep API_KEY ~/.crossenv
```

If the key is there, confirm there's no local `.env` file in the current directory that overrides it (a local `.env` takes precedence over `~/.crossenv`).

---

### WSL2 networking issues (corporate VPN / proxy)

If you're behind a corporate proxy, add proxy settings to `~/.bashrc`:

```bash
export http_proxy=http://proxy.example.com:8080
export https_proxy=http://proxy.example.com:8080
export no_proxy=localhost,127.0.0.1
```

Then `exec bash` and retry.

---

### `wsl --install` fails on older Windows 10

WSL2 requires Windows 10 version 1903 (build 18362) or later. Check your version:

```powershell
winver
```

If you're below 1903, update Windows first via **Settings → Windows Update**.

---

## 11. Learn more

- [Onboarding](Onboarding) — general setup guide (macOS / Linux)
- [AI Providers](ai-providers) — detailed notes on each provider, model options, rate limits
- [Cross-Stones Benchmark](cross-stones) — run and score the standard 10-domain benchmark
- [FAQ](faq) — common questions and troubleshooting

```bash
st-man                        # list all commands
st-man st-cross --web         # open the st-cross wiki page in your browser
```

