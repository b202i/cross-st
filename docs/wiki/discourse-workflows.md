# Discourse Posting Workflows

`st-post` publishes to any of your configured Discourse sites. This page covers
common workflows — from a quick single post to managing a full cross-product run.

---

## Before You Post

Your Discourse credentials live in `~/.crossenv`:

```
DISCOURSE_SITE=crossai.dev           ← startup default site
DISCOURSE={"sites":[{...},{...}]}    ← all sites; each entry is self-contained
```

Each site entry contains: `slug`, `url`, `username`, `api_key`, `category_id`,
`private_category_id`, `private_category_slug`. Nothing else is needed.

Set up with `st-admin --setup` or `st-admin --discourse-setup`.  
Manage categories with `st-admin --discourse`.

---

## Switching Between Sites

Inside `st`, the Post submenu key `n` cycles through your configured sites in
a round-robin:

```
st ai:gemini s:1 f:None Post> n
  Site → myforum   [crossai.dev, *myforum*, devforum, archive]
```

The selection persists for the rest of the `st` session. On next launch, `st`
returns to the site named in `DISCOURSE_SITE`.

From the CLI, pass `--site` directly:

```bash
st-post --site myforum top_10_ai.json
st-post --site crossai.dev -s 2 top_10_ai.json
```

---

## Workflow 1 — Private Draft → Edit in Place → Promote

**Best for:** polished single posts where you want a chance to review formatting
before the audience sees it.

```bash
# 1. Generate and check the report
st-gen top_10_ai.prompt                # writes top_10_ai.json
st-edit --view-only -s 1 top_10_ai.json   # browser preview before posting

# 2. Post to your private category (the default after --discourse-setup)
st-post -s 1 top_10_ai.json           # posts to your private category

# 3. Open the post in your browser, edit in place on Discourse if needed
#    — fix formatting, add images, adjust the title

# 4. From the Discourse post editor: change Category → your target category
#    and add relevant Tags, then Save
```

**Why private first:** Your private category is only visible to you and staff.
It gives you a clean preview of the rendered post (embeds, code blocks, audio
players) before it goes public.

---

## Workflow 2 — Direct Post to a Category

**Best for:** confident posts, automated pipelines, or test posts.

```bash
# Switch to your target category first
st-admin --discourse     # choose category 3 (custom ID) → enter your cat ID
# — or —
# set category_id directly in DISCOURSE JSON for a permanent change

st-post top_10_ai.json
```

Or one-liner without changing the default:

```bash
# Post story 1 to a specific site that already has the right category_id set
st-post --site devforum top_10_ai.json
```

---

## Workflow 3 — Fix → Post (Most Common)

**Best for:** taking the best story from a multi-AI run, fixing any errors, then
publishing.

```bash
# 1. Generate with all providers
st-bang top_10_ai.prompt           # parallel: all AI → top_10_ai.json

# 2. Pick the best story (st lists scores after bang)
st-ls top_10_ai.json               # see story scores

# 3. Fix with fact-check feedback
st-fact -s 2 top_10_ai.json        # fact-check story 2
st-fix  -s 2 top_10_ai.json        # apply fixes

# 4. Post the fixed story
st-post -s 2 top_10_ai.json
```

Inside `st` this is `g`→`b` (Bang), then `a`→`f` (fact-check), `e`→`x` (fix),
then `p`→`p` (post).

---

## Workflow 4 — Cross-Product 5×5 → Down-Select → Post

**Best for:** benchmark runs or when you want the definitive best story.

```bash
# 1. Generate all 25 combinations (5 stories × 5 AIs)
st-cross top_10_ai.prompt          # 5 stories × cross-fact-check all AI

# 2. View the leaderboard
st-verdict top_10_ai.json          # which AI + story scored highest

# 3. Down-select: post the winner
st-post -s 3 top_10_ai.json        # post story 3 (the winner)
```

**Tip:** 25 combinations → 30 total posts (25 stories + 5 cross-product
summaries) is usually too much. Pick 1–2 to share publicly.

---

## Workflow 5 — Companion Posts (Story + Fact-Check + Cross-Product)

**Best for:** full transparency — show readers both the report and how different
AIs rated its accuracy.

```bash
# Post the main report (story 1)
st-post -s 1 top_10_ai.json

# Post the fact-check as a reply to the main topic
st-post -s 1 -f 1 top_10_ai.json  # -f flag: post fact-check as a reply

# Optionally post the cross-product summary
st-post -s 5 top_10_ai.json        # story 5 is typically the cross-product report
```

Inside `st`: Post menu → `p` (post story), then `f` (post fact-check reply).

---

## Workflow 6 — Audio Report

**Best for:** sharing a spoken version of the report.

```bash
# Render to MP3 first
st-speak -s 1 top_10_ai.json       # writes top_10_ai.mp3

# Post with audio embed
st-post -s 1 top_10_ai.mp3 top_10_ai.json
```

Inside `st`: Post menu → `a` (post story with audio).

The MP3 is uploaded to Discourse and an audio player embed is prepended to the
post body automatically.

---

## Quick Reference

| Goal | Command |
|------|---------|
| Post story 1 to default site | `st-post file.json` |
| Post story 2 | `st-post -s 2 file.json` |
| Post to a specific site | `st-post --site myforum file.json` |
| Post with audio | `st-post -s 1 file.mp3 file.json` |
| Post fact-check as reply | `st-post -s 1 -f 1 file.json` |
| Verify credentials | `st-post --check` |
| Switch default site | `st-admin --discourse` |
| Change default site temporarily | `st` → `p` → `n` |
| See all site slugs | `st-admin --show` |

---

## Setting a Persistent Default Site

`DISCOURSE_SITE` in `~/.crossenv` controls which site `st` and `st-post` use on
startup. Change it with:

```bash
st-admin --discourse    # interactive — also lets you change default category
```

Or directly:

```bash
# Edit ~/.crossenv and set:
DISCOURSE_SITE=myforum
```

---

**Related:** [st-post](st-post.md) · [st-admin](st-admin.md) · [st-fix](st-fix.md) · [st-speak](st-speak.md)

