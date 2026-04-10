# st-admin — Manage settings, API keys, and templates

Manages your Cross settings: default AI provider, per-provider model overrides, TTS voice, editor, and prompt templates. Run once during setup, then whenever you want to switch providers.

**Related:** [st-new](st-new.md)  [AI Providers](ai-providers.md)  [TTS Audio](tts-audio.md)

---

## Community onboarding

`st-admin --setup` will offer to join the [crossai.dev](https://crossai.dev) community at the end of the wizard. You can also run it independently at any time:

```bash
st-admin --discourse-setup
```

This walks you through:
1. Displaying and accepting the crossai.dev Terms of Service
2. Opening `crossai.dev/signup` (or printing the URL) to create your account
3. Collecting your Discourse username
4. Provisioning your account (generates a per-user API key and private category)

The following keys are written to `~/.crossenv` on success:

| Key | Description |
|-----|-------------|
| `DISCOURSE_URL` | `https://crossai.dev` |
| `DISCOURSE_USERNAME` | Your Discourse username |
| `DISCOURSE_API_KEY` | Your per-user API key (for `st-post`) |
| `DISCOURSE_CATEGORY_ID` | Your private category ID |
| `DISCOURSE_PRIVATE_CATEGORY_SLUG` | Your private category slug |

To use a different provisioning server (dev/test):
```bash
DISCOURSE_PROVISION_URL=http://localhost:5000/api/provision-user st-admin --discourse-setup
```

---

## Discourse site manager

After completing `--discourse-setup`, use `--discourse` at any time to view your current Discourse configuration and switch the default posting category used by [`st-post`](st-post.md):

```bash
st-admin --discourse
```

### Interactive display

```
  Discourse Site Management
  ────────────────────────────────────────
  Site                          https://crossai.dev
  Username                      alice
  Default posting category      alice-private  [id=42]
  Private category              alice-private  [id=42]

  Change default posting category?
    1.  alice-private  (your private category)
    2.  Test (cleared daily)  — cleared daily, safe for testing
    3.  Enter a category ID manually
    q.  Keep current and exit

  Choice [q]: _
```

Selecting an option immediately updates `category_id` inside the `DISCOURSE` JSON in `~/.crossenv`. The change takes effect for the next `st-post` call — no restart required.

### Test (cleared daily) category

Option 2 targets the shared **`Test (cleared daily)`** sandbox on `crossai.dev` (category id=6):

- **Public read** — anyone can view posts without logging in
- **Login required to post** — you must have a registered account
- **Cleared nightly** — all posts are automatically deleted at 00:05 UTC by a server cron job
- The category name includes `(cleared daily)` so the behaviour is self-documenting

Use this category when you want to verify that `st-post` is working end-to-end without cluttering your private category.

### First-run migration

If you completed `--discourse-setup` but `st-post` is still failing, run `--discourse` once. On first run, if the flat `DISCOURSE_*` keys exist in `~/.crossenv` but the `DISCOURSE` JSON array (required by `st-post`) is absent, it is built and written automatically:

```
  ✓  Discourse configuration initialised from onboarding keys.
```

This closes the gap between provisioning and posting without requiring you to re-run setup.

### Flag comparison

| Flag | Purpose | When to use |
|------|---------|-------------|
| `--discourse-setup` | One-time account provisioning (T&C, API key, private category) | Once per user |
| `--discourse` | Show config; switch default posting category | Any time |

---

## For developers

Reads and writes `~/.crossenv` (global) and `.env` (repo-local). Model overrides are stored in `.ai_models`, one `provider=model` per line. `--init-templates` seeds `~/.cross_templates/` from the bundled `template/` directory.
