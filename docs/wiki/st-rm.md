# st-rm — Remove items from a story container

Removes a story or a fact-check entry from a `.json` container. Use `-s` to specify the story and `-f` to specify the fact-check.

## Examples

```bash
st-rm -s 3 subject.json              # remove story 3
st-rm -d 2 subject.json              # remove data item 2
st-rm -s 2 -f 1 subject.json         # remove fact-check 1 from story 2
st-rm -F -s 2 subject.json           # clear all fact-checks from story 2
st-rm -F --all-stories subject.json  # clear all fact-checks from every story
```

## Options

| Option | Description |
|--------|-------------|
| `file.json` | Path to the JSON container |
| `-d N`, `--data N` | Remove a data item by index |
| `-s N`, `--story N` | Remove a story by index |
| `-f N`, `--fact N` | Remove a fact-check report from a story by index |
| `-F`, `--clear-facts` | Clear all fact-checks (and segments) from a story (`-s`) or all stories |
| `--all-stories` | Apply `--clear-facts` to every story in the container |
| `-v`, `--verbose` | Verbose output |
| `-q`, `--quiet` | Minimal output |

**Related:** [st-ls](st-ls) · [st-cat](st-cat)

---

## For developers

Deletes data items, stories, or fact-check reports from a .json container.
Supports bulk-clearing all fact-checks and claim segments from one story or
every story in the container.


All index arguments are 1-based, matching the output of st-ls.
