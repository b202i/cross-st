# st-post — Post a story to Discourse

Publishes a story to your Discourse forum. Optionally attaches a fact-check as a reply. Use `--check` to verify your credentials without actually posting.

**Run after:** `st-prep`  `st-fix`  `st-merge`

---

## Examples

```bash
st-post subject.json                                      # post to Test (cleared daily) — safe default
st-post --category private subject.json                   # post to your private category (any site)
st-post --category reports subject.json                   # post to public 📄 Reports portfolio (crossai.dev)
st-post --category prompt-lab --prompt subject.json       # post the prompt to 🧪 Prompt Lab (crossai.dev)
st-post --category 42 subject.json                        # post to a category by numeric ID (any site)
st-post -s 2 subject.json                                 # post story 2
st-post -f 1 subject.json                                 # attach fact-check 1 as a reply
st-post --site MySite subject.json                        # post to a named Discourse site
st-post --check                                           # verify credentials without posting
```

## Options

| Option | Description |
|--------|-------------|
| `files` | Story `.json` file(s) to post |
| `--site {MMD,…}` | Discourse site to post to (default: `MMD`; site slug set in config) |
| `-s N`, `--story N` | Story to publish (1-based index, default: 1) |
| `-f N`, `--fact N` | Reply to the post with fact-check N |
| `--category VALUE` | Where to post — accepts `private`, a numeric category ID, or (on crossai.dev only) `test` / `reports` / `prompt-lab`. Default: `test`. See below. |
| `--prompt` | Post the prompt text from the container instead of the story (use with `--category prompt-lab`) |
| `--check` | Validate Discourse credentials and connection without posting |
| `-v`, `--verbose` | Verbose output |
| `-q`, `--quiet` | Minimal output |

### Posting categories

`--category` accepts three forms on every Discourse site:

| Value | Description |
|-------|-------------|
| `private` | Your personal private category — visible only to you. Resolves to `private_category_id` from your DISCOURSE config (works on every site). |
| `<number>` | Any Discourse category by numeric ID — works on every site. The escape hatch when you're not on crossai.dev or want a category outside the named shortcuts. |
| `test` · `reports` · `prompt-lab` | **crossai.dev only.** Friendly shortcuts for the three named categories on the crossai.dev community forum. On other Discourse sites these raise a clear error pointing you at numeric IDs. |

#### How to find a Discourse category numeric ID

Self-hosted forum, or a category not covered by the named shortcuts? Pass the numeric ID directly with `--category <number>`. Three quick ways to find it:

1. **In the Discourse web UI** — open the category page; the URL is `https://yourforum/c/<slug>/<id>` (the trailing number is the ID). Example: `https://forum.example.com/c/general/4` → id=`4`.
2. **From `/categories.json`** — open `https://yourforum/categories.json` in your browser (or `curl` it). Each entry has a numeric `id` field next to its `name` and `slug`.
3. **From `st-admin --discourse-setup` (when adding a new site)** — the wizard fetches `/site.json` from your forum and shows a numbered list of every category visible to your API key, with the Discourse category ID in parentheses. Pick by index or type the ID directly.

Once you know the ID, you can either:

- pass it ad-hoc with `st-post --category 4 …`, or
- store it as the persistent default for the active site via `st-admin --discourse` → option **5** (*Enter a category ID manually*).

#### crossai.dev shortcuts

| Shortcut | Discourse category | Notes |
|----------|--------------------|-------|
| `test` | `Test (cleared daily)` (id=6) | **Default.** Posts are deleted nightly at 00:05 UTC. Safe for testing `st-post` end-to-end. |
| `reports` | `📄 Reports` (id=16) | Public portfolio at `crossai.dev/u/<username>/activity/topics`. |
| `prompt-lab` | `🧪 Prompt Lab` (id=17) | Share prompts, get community feedback, collaborate on prompt engineering. |

> **Tip:** Default is `test`. Switch to `private` or `reports` once you're ready to keep the post.
> Use `st-admin --discourse` to change your persistent default category.

**Related:** [st-prep](st-prep)  [st-speak](st-speak)  [st-admin](st-admin)

---

## For developers

Site credentials are read from the `DISCOURSE` JSON in `~/.crossenv`. If an `.mp3` file is provided, it is uploaded first and the Discourse audio-player embed syntax is prepended to the post. `--category` resolution is centralised in `discourse.resolve_category(site, name_or_id)`: numeric IDs pass through, `private` resolves to `site["private_category_id"]`, and the crossai.dev shortcuts (`test`/`reports`/`prompt-lab` → 6/16/17) are gated on `crossai.dev` appearing in `site["url"]`. The shortcut table lives in `cross_st/discourse.py` as `CROSSAI_NAMED_CATEGORIES`.
