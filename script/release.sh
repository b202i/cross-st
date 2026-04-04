#!/usr/bin/env bash
# script/release.sh — Build, publish to PyPI, tag, and push cross-st.
#
# Usage:
#   bash script/release.sh          # reads version from pyproject.toml
#   bash script/release.sh --dry    # build only, skip twine upload and git push
#
# Prerequisites:
#   pip install build twine          (or: pipx inject cross-st build twine)
#   twine credentials in ~/.pypirc or TWINE_USERNAME / TWINE_PASSWORD env vars
#
# What this script does:
#   1. Confirms the working tree is clean (no uncommitted changes)
#   2. Runs the test suite
#   3. Deletes stale dist/ artefacts
#   4. Builds sdist + wheel with python -m build
#   5. Checks the distributions with twine check
#   6. Uploads to PyPI with twine upload
#   7. Tags the release (v<version>) and pushes tag + branch to origin
#   8. Pushes the GitHub Wiki  (WIKI_SSH=1 if your SSH key is configured)
#
# After publishing, run:
#   bash script/smoke_test.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

DRY=0
if [[ "${1:-}" == "--dry" ]]; then
    DRY=1
    echo "  ⚠️  --dry mode: build + check only, no upload or git push"
fi

# ── Helpers ────────────────────────────────────────────────────────────────────
_section() { echo; echo "  ── $1 ──────────────────────────────────────────────"; }
_ok()      { echo "  ✅  $1"; }
_err()     { echo "  ❌  $1" >&2; exit 1; }

# ── Read version from pyproject.toml ──────────────────────────────────────────
VERSION="$(python3 -c "
import tomllib, pathlib
with open('pyproject.toml', 'rb') as f:
    d = tomllib.load(f)
print(d['project']['version'])
" 2>/dev/null || python3 -c "
import re, pathlib
m = re.search(r'^version\s*=\s*\"([^\"]+)\"', pathlib.Path('pyproject.toml').read_text(), re.M)
print(m.group(1)) if m else exit(1)
")"

echo
echo "  Cross release script"
echo "  ─────────────────────────────────────────────────────"
echo "  Package  : cross-st"
echo "  Version  : $VERSION"
echo "  Tag      : v${VERSION}"
[[ $DRY -eq 1 ]] && echo "  Mode     : DRY RUN (no upload, no push)" || echo "  Mode     : LIVE"
echo "  ─────────────────────────────────────────────────────"

read -r -p "  Continue? [y/N]: " ans
[[ "${ans}" == "y" || "${ans}" == "Y" ]] || { echo "  Cancelled."; exit 0; }

# ── 1. Clean working tree ─────────────────────────────────────────────────────
_section "1. Working tree"
if [[ -n "$(git status --porcelain)" ]]; then
    echo
    git status --short
    echo
    _err "Uncommitted changes. Commit or stash them first."
fi
_ok "Working tree is clean"

# ── 2. Tests ──────────────────────────────────────────────────────────────────
_section "2. Test suite"
python3 -m pytest tests/ -q --tb=short
_ok "All tests pass"

# ── 3. Clean dist/ ────────────────────────────────────────────────────────────
_section "3. Clean dist/"
rm -rf dist/ build/ cross_st.egg-info/
_ok "Stale artefacts removed"

# ── 4. Build ──────────────────────────────────────────────────────────────────
_section "4. Build sdist + wheel"
python3 -m build
_ok "Build complete"
ls -lh dist/

# ── 5. Twine check ────────────────────────────────────────────────────────────
_section "5. twine check"
python3 -m twine check dist/*
_ok "Distribution checks passed"

if [[ $DRY -eq 1 ]]; then
    echo
    echo "  ── DRY RUN COMPLETE ───────────────────────────────────────────"
    echo "  Artefacts are in dist/ — inspect them, then re-run without --dry"
    echo
    exit 0
fi

# ── 6. Upload to PyPI ─────────────────────────────────────────────────────────
_section "6. twine upload → PyPI"
python3 -m twine upload dist/*
_ok "Uploaded to PyPI: https://pypi.org/project/cross-st/${VERSION}/"

# ── 7. Tag and push ───────────────────────────────────────────────────────────
_section "7. Tag v${VERSION} and push"
git tag "v${VERSION}"
git push origin HEAD
git push origin "v${VERSION}"
_ok "Tag v${VERSION} pushed to origin"

# ── 8. Wiki ───────────────────────────────────────────────────────────────────
_section "8. Push GitHub Wiki"
WIKI_SSH="${WIKI_SSH:-0}" bash script/push_wiki.sh "release v${VERSION}"
_ok "Wiki updated"

# ── Done ──────────────────────────────────────────────────────────────────────
echo
echo "  ─────────────────────────────────────────────────────"
echo "  ✅  cross-st ${VERSION} released!"
echo
echo "  PyPI  : https://pypi.org/project/cross-st/${VERSION}/"
echo "  Tag   : v${VERSION}"
echo "  Wiki  : https://github.com/b202i/cross-st/wiki"
echo
echo "  Next: wait ~60s for PyPI to propagate, then run:"
echo "    bash script/smoke_test.sh ${VERSION}"
echo

