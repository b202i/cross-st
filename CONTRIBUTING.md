# Contributing to Cross

Thank you for your interest in contributing! Cross is an AI-powered
cross-product fact-checking and story generation tool. Contributions of
all kinds are welcome — bug fixes, new features, documentation, and tests.

---

## Getting Started

### Prerequisites
- **Python 3.11** exactly (3.12+ is not supported — audio packages lack
  pre-built wheels for macOS ARM on newer Python versions)
- Git
- API keys for at least one AI provider (see `.env.example`)

### Clone and Set Up

```bash
git clone https://github.com/b202i/cross-st.git
cd cross
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
bash script/symbolic_links.bash
cp .env.example .env
# Edit .env with your API keys
```

For a complete walkthrough see [README_install.md](README_install.md).

### Verify Your Setup

```bash
pytest tests/ -v
st --help
```

---

## How to Contribute

### Reporting Bugs

1. Check [existing issues](https://github.com/b202i/cross-st/issues) first
2. Open a new issue using the **Bug Report** template
3. Include: Python version, OS, the exact command you ran, and the full
   traceback

### Requesting Features

1. Open an issue using the **Feature Request** template
2. Describe the use case, not just the solution
3. Check if there's an existing related command (e.g., `st-bang`, `st-fix`,
   `st-merge`) that could be extended

### Submitting Pull Requests

1. Fork the repo and create a branch:
   ```bash
   git checkout -b feature/my-feature
   ```
2. Make your changes
3. Add or update tests in `tests/`
4. Run the test suite:
   ```bash
   pytest tests/ -v
   ```
5. Open a Pull Request against `main`

---

## Project Structure

```
st-*.py          CLI commands (st-gen, st-fact, st-merge, st-fix, etc.)
st.py            Interactive TUI menu
ai_*.py          AI provider handlers (openai, anthropic, gemini, xai, perplexity)
ai_handler.py    Unified AI dispatch layer — all AI calls go through here
base_handler.py  Shared handler base class
discourse.py     Discourse API integration
mmd_*.py         Multimedia / audio / plotting utilities
tests/           pytest test suite
template/        Default prompt templates
script/          Install and utility scripts
assets/          Icons and static assets
```

### The AI Handler Pattern

All AI calls must go through `ai_handler.py`. This ensures:
- Consistent caching behavior (`--cache` / `--no-cache`)
- Error handling and retry logic
- Timing data collection for `st-speed`

Never call an AI provider SDK directly from a command script. Always use:
```python
from ai_handler import process_prompt
response = process_prompt(ai_name, prompt, verbose, use_cache)
```

---

## Coding Style

- Python 3.11 compatible
- PEP 8 (use `black` or any formatter — consistency over style preference)
- Type hints encouraged but not required
- Keep CLI output clean: use the existing table/progress patterns from
  other `st-*` commands
- All user-facing error messages should suggest a fix (see `README_error_handling.md`)

---

## Adding a New AI Provider

1. Create `ai_<name>.py` following the pattern of `ai_openai.py`
2. Implement `get_cached_response()` and `put_content()`
3. Register the provider in `ai_handler.py`
4. Add the API key to `.env.example` with a placeholder
5. Test with `st-gen --ai <name> my_topic.prompt`

---

## Adding a New `st-*` Command

1. Create `st-mycommand.py` in the project root
2. Add `#!/usr/bin/env python3` at the top
3. Run `bash script/symbolic_links.bash` to create the symlink
4. Document with a `--help` argparse description
5. Add a test in `tests/`

---

## Running Tests

```bash
# All tests
pytest tests/ -v

# Specific file
pytest tests/test_st_speed.py -v

# With coverage
pytest tests/ --cov=. --cov-report=html
open htmlcov/index.html
```

Tests that require live AI API calls are marked `@pytest.mark.live` and
are skipped by default. Run them with:
```bash
pytest tests/ -m live
```

---

## Questions?

Open a [Discussion](https://github.com/b202i/cross-st/discussions) for general
questions, or an Issue for bugs and feature requests.

