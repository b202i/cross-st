# st-fact — Fact-check stories in a container

Sends a single story to an AI and asks it to fact-check every claim, scoring each one true, partially true, or false. Appends the result to the container.

**Run after:** `st-prep`    **Run before:** `st-fix`  `st-heatmap`

```bash
st-fact subject.json                    # fact-check story 1 with default AI
st-fact -s 2 --ai gemini subject.json  # fact-check story 2 with Gemini
st-fact --no-cache subject.json        # bypass API cache
st-fact --ai-review subject.json       # AI digest of existing fact-check results
st-fact subject.json                    # fact-check story 1 with default AI
st-fact --ai-short subject.json        # short caption from existing fact-check data
st-fact --all subject.json              # fact-check all stories in the container
st-fact --ai-summary subject.json      # concise summary from existing fact-check data
st-fact --ai all subject.json           # run all AIs in parallel (one per story)
st-fact --ai-review subject.json        # AI digest of existing fact-check results
st-fact --ai-short subject.json         # short caption from existing fact-check data
st-fact --ai-caption subject.json       # detailed caption from existing fact-check data
st-fact --ai-summary subject.json       # concise summary from existing fact-check data
st-fact --ai-story subject.json         # comprehensive story from existing fact-check data
st-fact --ai-title subject.json         # title from existing fact-check data
st-fact --file subject.json             # write results to a file
st-fact --timeout 30 subject.json       # 30-second timeout per paragraph segment

## For developers

Splits the story into segments via `mmd_util.build_segments()`, sends them to the AI, and appends a `fact[]` entry to the container. The entry includes `score`, `counts`, `summary`, `claims[]` (per-segment verdicts), and `timing{}`.
