# Cross Wiki

*AI checking AI.*

Cross generates research reports using up to 5 AI providers simultaneously, then cross-checks every report against all others — a 5×5 fact-check matrix. Reports can be published to Discourse.

---

## Getting started

New user? Start here: **[Onboarding](Onboarding)** — set up your API keys and run your first report in minutes.

---

## Command reference

| Command | Description |
|---------|-------------|
| [st](st) | Interactive menu — launch any command from a numbered list |
| [st-admin](st-admin) | Settings manager: DEFAULT_AI, model overrides, TTS voice, editor |
| [st-analyze](st-analyze) | AI-powered analysis of cross-product fact-check data |
| [st-bang](st-bang) | Parallel report generation — run all AIs at once |
| [st-cat](st-cat) | Print story fields to stdout (pipe-friendly) |
| [st-cross](st-cross) | Cross-product: generate N stories × fact-check with N AIs |
| [st-domain](st-domain) | Interactive wizard: create a new Cross-Stones benchmark domain |
| [st-edit](st-edit) | Open a story container in your editor |
| [st-fact](st-fact) | Fact-check one story with one AI |
| [st-fetch](st-fetch) | Import external content (URL, tweet, clipboard, file) |
| [st-find](st-find) | Search across story containers and prompt files |
| [st-fix](st-fix) | Improve a story using fact-check feedback |
| [st-gen](st-gen) | Generate a single AI report |
| [st-heatmap](st-heatmap) | Cross-product fact-check score heatmap |
| [st-ls](st-ls) | List contents of a story container |
| [st-man](st-man) | Manual pages for Cross commands (this system) |
| [st-merge](st-merge) | Synthesize multiple AI stories into one |
| [st-new](st-new) | Create a new prompt from a template |
| [st-plot](st-plot) | Cross-product fact-check score plots |
 [st-post](st-post)  Post a story to Discourse 
 [discourse-workflows](discourse-workflows)  Discourse posting workflow guide 
| [st-prep](st-prep) | Prepare a raw AI response for posting |
| [st-read](st-read) | Readability metrics for stories |
| [st-rm](st-rm) | Remove items from a story container |
| [st-speak](st-speak) | Render a story as spoken audio (MP3) |
| [st-speed](st-speed) | AI performance and speed analysis |
| [st-stones](st-stones) | Cross-Stones benchmark leaderboard |
| [st-verdict](st-verdict) | Verdict category bar chart |
| [st-voice](st-voice) | Browse, download, and test Piper TTS voices |

---

## Topics

- [Onboarding](Onboarding) — first-time setup, API keys, running your first report
- [Container Format](Container-Format) — anatomy of `subject.json`: `data[]`, `story[]`, `fact[]`, timing
- [AI Providers](ai-providers) — all 5 providers, models, free vs paid tiers
- [Cross-Stones Benchmark](cross-stones) — benchmark suite: scoring, domains, leaderboard
- [FAQ](faq) — common questions and troubleshooting

---

## Install

```bash
pipx install cross-st          # no TTS
pipx install "cross-st[tts]"   # with text-to-speech
st-admin --setup              # configure API keys → ~/.crossenv
```

Source: [github.com/b202i/cross-st](https://github.com/b202i/cross-st)

