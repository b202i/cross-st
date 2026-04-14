# st-print — Convert a story to PDF and print or save

Exports a story as a PDF, or sends it directly to a printer. Use `--save-pdf` to save the file without printing.

**Run after:** `st-prep`

## Examples

```bash
st-print subject.json                      # print story 1 to default printer
st-print --save-pdf subject.json           # save as subject.pdf (auto-named)
st-print --output report.pdf subject.json  # save to an explicit filename
st-print -s 2 subject.json                # print story 2
st-print --all subject.json               # print all stories (one PDF each)
st-print --preview subject.json           # save PDF then open in viewer
st-print --printer "HP_LaserJet" s.json   # send to a specific printer
```

**Options:** `-s`  `story`  `--all`  `--save-pdf`  `--output`  `FILE`  `--preview`  `--printer`  `-v`  `-q`

**Related:** [st-post](st-post) · [st-edit](st-edit)

---

## For developers

Pipeline: Markdown → HTML (via `mistune`) → PDF (via `WeasyPrint`). `--preview` opens the PDF in the system viewer before printing.
