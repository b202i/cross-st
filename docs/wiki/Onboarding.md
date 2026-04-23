# Onboarding — Getting Started with Cross

Cross generates research reports using up to 5 AI providers simultaneously, then cross-checks every report against all the others. This page walks you through setup from zero to your first report.

> **Windows users:** see the dedicated [Windows / WSL2](Windows-WSL2) guide.

---

## 1. Install Cross

```bash
pipx install "cross-st[tts]"
```

If pipx says it's already installed, add `--force`:

```bash
pipx install --force "cross-st[tts]"
```

To install without TTS (`st-speak` / `st-voice` unavailable):

```bash
pipx install cross-st
```

## 2. Reload your shell

```bash
pipx ensurepath && exec zsh
```

If `st` or any `st-*` command is not found after install, this is the fix. It adds `~/.local/bin` to your PATH and reloads the shell.

---

## 3. Get an API key

You need at least one API key. **Start with Gemini — it's free.**

### ⭐ Google Gemini — Free tier (recommended for new users)

No credit card required. Just a Google account.

1. Go to [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Click **Create API key**
3. Copy the key — it starts with `AIza...`

Free tier limits: 15 requests/minute, 1,500 requests/day, 1 million tokens/day — more than enough to explore Cross.

Default model: `gemini-2.5-flash` — fast, capable, 1M context window.

---

### xAI (Grok)

1. Sign up at [console.x.ai](https://console.x.ai)
2. Create an API key in the dashboard
3. Key starts with `xai-...`

Default model: `grok-4-1-fast-reasoning`

> xAI offers limited free credits for new accounts; check the console for your current balance.

---

### Anthropic (Claude)

1. Sign up at [console.anthropic.com](https://console.anthropic.com)
2. Add a payment method (credit card required)
3. Create an API key in **API Keys**

Default model: `claude-opus-4-5`

Pricing: pay-per-token. Typical Cross report: ~$0.01–0.05 depending on model.

---

### OpenAI (GPT)

1. Sign up at [platform.openai.com](https://platform.openai.com)
2. Add a payment method (credit card required)
3. Go to **API keys** → **Create new secret key**

Default model: `gpt-4o`

Pricing: pay-per-token. Free tier was removed — a small prepaid credit is required.

---

### Perplexity (Sonar)

1. Sign up at [perplexity.ai](https://www.perplexity.ai)
2. Go to **Settings → API** → **Generate**
3. Key starts with `pplx-...`

Default model: `sonar-pro`

Perplexity Sonar models include **live web search with citations** — useful for current-events reporting. Requires a paid plan or API credits.

---

## 4. Configure Cross

Run the setup wizard:

```bash
st-admin --setup
```

The wizard will prompt you for each API key (press Enter to skip any), ask which provider to use as your default, and write everything to `~/.crossenv`.

Or configure manually:

```bash
st-admin --set DEFAULT_AI gemini
st-admin --set GEMINI_API_KEY AIza...
```

Settings are stored in `~/.crossenv`. You can also create a local `.env` in any working directory — it takes precedence over `~/.crossenv`, which is useful for per-project overrides.

---

## 5. Run your first report

```bash
mkdir my_reports && cd my_reports
st-new                        # create a prompt from the default template
                              # opens your editor — describe your topic, save
st-bang                       # generate reports from all configured AIs in parallel
st-ls report.json             # inspect the container
st-cross report.json          # cross-check every story against every other AI
st-heatmap report.json        # visualise the fact-check score matrix
```

Or step by step:

```bash
st-gen report.json            # generate one report (uses DEFAULT_AI)
st-gen --ai gemini report.json
st-fact --ai anthropic report.json -s 1   # fact-check story 1 with Claude
```

---

## 6. Useful configuration commands

```bash
st-admin                        # show current settings
st-admin --set DEFAULT_AI xai   # switch default provider
st-admin --model xai grok-3     # pin a specific model for a provider
st-admin --list-models          # show all configured model overrides
```

---

## 7. Learn more

```bash
st-man                          # list all commands
st-man st-cross                 # local help for st-cross
st-man st-cross --web           # open the st-cross wiki page
```

- [Windows / WSL2](Windows-WSL2) — complete setup guide for Windows users
- [AI Providers](ai-providers) — detailed notes on each provider, model options, rate limits
- [Cross-Stones Benchmark](cross-stones) — run and score the standard 10-domain benchmark
- [FAQ](faq) — common questions and troubleshooting

