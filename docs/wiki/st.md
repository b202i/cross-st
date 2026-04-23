# st — Interactive menu launcher

Run `st` in the directory containing your story file and you get a keyboard-driven menu that walks you through the full workflow — no flags to memorize.

```bash
st               # open the menu (auto-detects *.json in current directory)
st topic.json    # open with a specific story pre-selected
```

The menus follow the natural top-down workflow:

| Key | Menu | What it covers |
|-----|------|----------------|
| `g` | Generate | Write a prompt, generate stories, run all AIs in parallel |
| `v` | View | Inspect stories and fact-checks |
| `e` | Edit | Revise story text, title, improve with AI |
| `a` | Analyze | Fact-check, cross-check all AIs, benchmark |
| `p` | Post | Publish to Discourse, export or print PDF |
| `u` | Utility | Charts, audio, remove stories |
| `x` | Settings | Default AI, voice, editor |

Press a letter to enter a submenu, then a second letter to build the command. Press `RETURN` to run it, `ESC` to go back.

## Keyboard shortcuts

These work at any menu level, at any time:

| Key | Action |
|-----|--------|
| `RETURN` | Execute the current command |
| `ESC` | Go back to the previous menu (or quit if already at the top) |
| `Ctrl+U` | **Clear the current command** — the fastest way to undo a mis-press |
| `←` / `DELETE` | Enter edit mode — move the cursor and tweak the command before running |
| `?` | Redisplay the current menu |
| `A` | Cycle to the next AI provider (global, works in any submenu) |
| `S` | Cycle to the next story |
| `F` | Cycle to the next fact-check |

### About Ctrl+C

`^C` interrupts the currently *running* `st-*` command and returns you to the `st` prompt — it does **not** quit `st` itself. It's safe to use if a long-running job (e.g. `st-bang`, `st-cross`) takes too long or you realise it's the wrong command.

For simply undoing a mis-selected menu item (before pressing RETURN), use **`Ctrl+U`** instead — it clears the command line instantly without interrupting anything.

## Options

| Option | Description |
|--------|-------------|
| `file.json / file.prompt` | Path to the story container or prompt file (auto-detected if only one exists in CWD) |
| `--site {MMD,DIYRV,Shang}` | Discourse site to use for posting; overrides `DISCOURSE_SITE` in config |
| `-a`, `--ai {xai,anthropic,openai,perplexity,gemini}` | AI provider to start with; overrides `DEFAULT_AI` |
| `-b`, `--bang` | Start the parallel generator (`st-bang`) instead of single-AI generation |
| `-q`, `--quiet` | Minimal output |
| `-v`, `--verbose` | Verbose output |

**Related:** [Onboarding](Onboarding)  [st-new](st-new)  [st-bang](st-bang)  [Command Reference](Home)

---

## For developers

`st.py` builds shell commands only — no business logic lives here. Every action calls a `st-*.py` tool directly. You can always skip the menu and run any `st-*` command by hand.

### Adding a command to a menu

1. Add a label in the relevant submenu dict in `menus` (~line 40):
   ```python
   "k": "Description shown in menu"
   ```
2. Add the matching `case` in `execute_menu()`:
   ```python
   case "k":
       cmd = f"st-mycommand {file_json}"
   ```
3. If the command writes to the `.json` container, add its name to `POST_CMD_REFRESH` at the top of the file — this tells `st` to re-read the file after the command finishes so story/fact-check counts stay current.
