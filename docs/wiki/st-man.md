# st-man — Show help for any st-* command

Shows the built-in help page for any `st-*` command, like the Linux `man` command. Add `--web` to open the full documentation page in your browser.

---

## Examples

```bash
st-man st-gen                  # show help for st-gen in the terminal
st-man st-gen --web            # open the st-gen wiki page in your browser
st-man st-gen --doc            # show the raw module docstring
st-man --web                   # open the wiki home page in your browser
st-man faq --web               # open the FAQ wiki page
```

## Options

| Option | Description |
|--------|-------------|
| `command` | Any `st-*` command name (e.g. `st-gen`, `st-cross`) or topic (`onboarding`, `ai-providers`, `cross-stones`, `faq`) |
| `--web` | Open the full wiki page in the default browser instead of printing to terminal |
| `--doc` | Print the raw module docstring (unformatted) |

**Related:** [Home](Home)

---

## For developers

Extracts help text from the module docstring of each `st-*.py` file at runtime — no separate help database. Documentation pages live in `docs/wiki/` and are served directly from the GitHub repo; no wiki plan required.
