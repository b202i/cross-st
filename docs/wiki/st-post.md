# st-post — Post a story to Discourse

Publishes a story to your Discourse forum. Optionally attaches a fact-check as a reply. Use `--check` to verify your credentials without actually posting.

**Run after:** `st-prep`  `st-fix`  `st-merge`

---

## Examples

```bash
st-post subject.json                              # post to Test (cleared daily) — safe default
st-post --category private subject.json           # post to your private category
st-post --category reports subject.json           # post to public 📄 Reports portfolio
st-post --category prompt-lab subject.json        # post to 🧪 Prompt Lab
st-post -s 2 subject.json                         # post story 2
st-post -f 1 subject.json                         # attach fact-check 1 as a reply
st-post --site MySite subject.json                # post to a named Discourse site
st-post --check                                   # verify credentials without posting
```

## Options

| Option | Description |
|--------|-------------|
| `files` | Story `.json` file(s) to post |
| `--site {MMD,…}` | Discourse site to post to (default: `MMD`; site slug set in config) |
| `-s N`, `--story N` | Story to publish (1-based index, default: 1) |
| `-f N`, `--fact N` | Reply to the post with fact-check N |
| `--category {private,test,reports,prompt-lab}` | Posting destination (default: `test` — see table below) |
| `--check` | Validate Discourse credentials and connection without posting |
| `-v`, `--verbose` | Verbose output |
| `-q`, `--quiet` | Minimal output |

### Posting categories

| Category | Description |
|----------|-------------|
| `test` | **Default.** `Test (cleared daily)` sandbox (id=6) — posts deleted nightly at 00:05 UTC. Safe for testing `st-post` end-to-end. |
| `private` | Your personal private category — visible only to you. Posts persist. |
| `reports` | `📄 Reports` (id=16) — public portfolio at `crossai.dev/u/<username>/activity/topics`. Posts are publicly visible. |
| `prompt-lab` | `🧪 Prompt Lab` (id=17) — share prompts, get community feedback, collaborate on prompt engineering. |

> **Tip:** Default is `test`. Switch to `private` or `reports` once you're ready to keep the post.
> Use `st-admin --discourse` to change your persistent default category.

**Related:** [st-prep](st-prep)  [st-speak](st-speak)  [st-admin](st-admin)

---

## For developers

Site credentials are read from the `DISCOURSE` JSON in `.env`. If an `.mp3` file is provided, it is uploaded first and the Discourse audio-player embed syntax is prepended to the post. The `reports` category maps to `_DISCOURSE_REPORTS_CATEGORY_ID = 16` and `prompt-lab` to `_DISCOURSE_PROMPT_LAB_CATEGORY_ID = 17` in `st-admin.py`.
