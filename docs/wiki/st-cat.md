# st-cat — Print story container fields to stdout

Prints the raw JSON contents of a story container to the terminal. Useful for debugging or piping to other tools.

## Examples

```bash
st-cat -t subject.json              # print title of story 1
st-cat --markdown -s 3 subject.json # print markdown of story 3
st-cat -f 2 -s 1 subject.json       # print fact-check report 2 from story 1
st-cat --text -s 2 subject.json     # print plain text body of story 2
```

## Options

| Option | Description |
|--------|-------------|
| `-s N`, `--story N` | Story number to read (integer), default: `1` |
| `-f N`, `--fact N` | Fact-check report number to read (integer); prints the specified fact-check instead of a story |
| `--title`, `-t` | Print the story title |
| `--text` | Print the plain-text story body |
| `--markdown` | Print the story markdown |
| `--hashtags` | Print the story hashtags |
| `--spoken` | Print the story spoken-text variant |
| `-v`, `--verbose` | Verbose output |
| `-q`, `--quiet` | Minimal output |

**Related:** [st-ls](st-ls) · [st-edit](st-edit)

---

## For developers

Reads a single story (or fact-check) from a .json container and prints the
requested field(s) to standard output.  Useful for piping story text into
other tools or shell scripts.
