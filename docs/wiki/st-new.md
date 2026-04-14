# st-new — Start a new report from a prompt template

Creates a fresh prompt file from a template and opens your editor so you can fill in the topic. The starting point for every new research report.

**Run before:** `st-gen` · `st-bang`

## Examples

```bash
st-new subject                          # create prompt, open editor
st-new -g subject                       # create, edit, then run st-gen + st-prep automatically
st-new -g --ai gemini subject           # same, using a specific AI provider
st-new --template custom subject        # use a named template
st-new --bang subject                   # edit then run st-bang (all AIs)
```

**Options:** `--template`  `-g/--gen`  `--ai`  `--bang`  `--st`  `--no-spell`  `-v`  `-q`

**Related:** [st-gen](st-gen) · [st-bang](st-bang) · [st-admin](st-admin)

---

## For developers

Template resolution order: `./template/` (CWD) → `~/.cross_templates/` → `<script-dir>/template/`. After editing, optionally launches `st-bang` automatically. `st-admin --init-templates` seeds `~/.cross_templates/` for pip/pipx installs.
