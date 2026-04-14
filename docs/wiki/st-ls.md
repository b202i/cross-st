# st-ls — List the contents of a story container

Lists the stories and fact-checks stored inside a `.json` container — titles, AI authors, scores, and timestamps.

## Examples

```bash
st-ls subject.json              # default: story table (titles, scores, flags)
st-ls -a subject.json           # show all: data, stories, fact-checks, claims
st-ls --data subject.json       # raw API data items only
st-ls --fact subject.json       # fact-check summary table
st-ls -C subject.json           # cross-AI claims comparison table
st-ls --fact -C subject.json    # fact-check table + claims
```

## Options

| Option | Description |
|--------|-------------|
| `-d`, `--data` | Display raw API data items |
| `-s`, `--story` | Display the stories section (titles, scores, flags) |
| `-f`, `--fact` | Display the fact-check summary table |
| `-C`, `--claims` | Display the cross-AI claims comparison table (segment × AI verdict) |
| `-c N`, `--clip N` | Clip displayed title length to N characters (default: 60) |
| `-a`, `--all` | Display all sections: data, stories, fact-checks, and claims |
| `-v`, `--verbose` | Verbose output |
| `-q`, `--quiet` | Minimal output |

**Related:** [st-cat](st-cat) · [st-edit](st-edit)

---

## For developers

List stories, data, and fact-checks inside a `.json` container.
Default shows the story table — a quick overview of all stories and their
fact-check scores, much like the Linux `ls` command gives a directory listing.
Use `-a` / `--all` to show every section, or combine flags as needed.

Run after:  st-gen   (generated your first story)
            st-bang  (generated from all AI providers)
            st-cross (ran the cross-product fact-check)
            st-fact  (ran a single fact-check)
Run before: st-print  (preview or print a story)
            st-fact   (fact-check a story)
            st-cross  (cross-check all stories)
            st-post   (publish a story)


## Story table columns

| Column | Meaning |
|--------|---------|
| S      | Story index (use with -s N in other commands) |
| Flag   | Story origin: blank = original AI output; [fix:patch/best/synth] = improved by st-fix; [merge] = synthesized by st-merge |
| Segs   | Number of fact-checkable segments extracted from the story |
| Score  | Average fact-check score across all evaluators (higher = more accurate; max 200 for 10 claims at 20 pts each) |

Run `st-fact` or `st-cross` to populate the Score column.

## See also

- st-fact   — fact-check a single story against one AI evaluator
- st-cross  — cross-product N×N fact-check (every AI checks every story)
- st-read   — display the full text of a story
- st-cat    — dump the raw JSON container
