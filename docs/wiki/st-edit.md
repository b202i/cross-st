# st-edit — Edit or view story fields in a container

Opens any field in a story container — story text, title, spoken version, or a fact-check — in your configured editor. Changes are saved back to the `.json` file.

**Run after:** `st-prep`

---

## Examples

```bash
st-edit subject.json                    # edit story 1 markdown in $EDITOR
st-edit -s 2 subject.json              # edit story 2
st-edit --markdown subject.json        # edit the markdown field of story 1
st-edit --title subject.json           # edit the title field
st-edit --text subject.json            # edit the plain-text field
st-edit --spoken subject.json          # edit the spoken-audio source text
st-edit -f 1 subject.json             # edit fact-check report 1
st-edit --view subject.json            # view story with Glow, then open editor
st-edit --view-only subject.json       # view story with Glow (read-only)
```

## Options

| Option | Description |
|--------|-------------|
| `file.json` | Path to the JSON container |
| `-s N`, `--story N` | Story to edit (1-based index, default: 1) |
| `-f N`, `--fact N` | Fact-check report to edit (1-based index) |
| `-md`, `--markdown` | Edit the Markdown field |
| `-title`, `--title` | Edit the title field |
| `-text`, `--text` | Edit the plain-text field |
| `-spoken`, `--spoken` | Edit the text-to-speech source text |
| `--view` | View with Glow first, then open editor |
| `--view-only` | View with Glow only — no editing |
| `-q`, `--quiet` | Minimal output |
| `-v`, `--verbose` | Verbose output |

**Related:** [st-prep](st-prep)  [st-fix](st-fix)  [st-admin](st-admin)

---

## For developers

Reads the targeted field from the `story[]` array, writes it to a temp file, opens `$EDITOR`, then writes the saved content back. For `--fact`, reads from `fact[].summary` or the full fact report JSON.
