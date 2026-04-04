#!/usr/bin/env bash
# script/push_wiki.sh — Push docs/wiki/ pages to the GitHub Wiki repo.
#
# The GitHub Wiki is a separate git repo at:
#   https://github.com/b202i/cross.wiki.git   (HTTPS — needs credential helper)
#   git@github.com:b202i/cross.wiki.git        (SSH   — preferred; set WIKI_SSH=1)
#
# This script:
#   1. Clones (or pulls) the wiki repo into /tmp/cross-wiki/
#   2. Copies all docs/wiki/*.md files into it
#   3. Commits and pushes
#
# Usage:
#   bash script/push_wiki.sh
#   bash script/push_wiki.sh "update st-man page"   # custom commit message
#   WIKI_SSH=1 bash script/push_wiki.sh             # use SSH remote (recommended)
#
# First-time setup — GitHub creates the wiki repo lazily.  Before running this
# script on a fresh repo you must initialise it once via the GitHub UI:
#   1. Go to https://github.com/b202i/cross/wiki
#   2. Click "Create the first page", save with any content
#   3. Then re-run this script — it will overwrite that placeholder page

set -euo pipefail

WIKI_HTTPS="https://github.com/b202i/cross.wiki.git"
WIKI_SSH_URL="git@github.com:b202i/cross.wiki.git"
WIKI_REPO="${WIKI_HTTPS}"
if [ "${WIKI_SSH:-0}" = "1" ]; then
    WIKI_REPO="${WIKI_SSH_URL}"
fi

WIKI_TMP="/tmp/cross-wiki"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WIKI_SRC="${REPO_ROOT}/docs/wiki"
MSG="${1:-sync wiki from docs/wiki/}"

echo "→ Building auto-generated pages..."
_PYTHON="${PYTHON:-}"
if [[ -z "$_PYTHON" ]]; then
    if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
        _PYTHON="${REPO_ROOT}/.venv/bin/python"
    else
        _PYTHON="python3"
    fi
fi
"$_PYTHON" "${REPO_ROOT}/script/build_wiki.py"

if [ -d "${WIKI_TMP}/.git" ]; then
    echo "→ Pulling existing wiki clone..."
    git -C "${WIKI_TMP}" pull --quiet
else
    echo "→ Cloning wiki repo..."
    if ! git clone "${WIKI_REPO}" "${WIKI_TMP}" 2>&1; then
        echo ""
        echo "✗ Could not clone the GitHub Wiki repo."
        echo "  GitHub creates the wiki repo lazily — it only exists after"
        echo "  the first page is created through the GitHub UI."
        echo ""
        echo "  One-time setup (do this once, then re-run this script):"
        echo "    1. Go to https://github.com/b202i/cross/wiki"
        echo "    2. Click 'Create the first page', save with any content"
        echo "    3. Re-run:  bash script/push_wiki.sh"
        echo "       (HTTPS is fine — credentials are already cached by git)"
        echo ""
        echo "  If you got 'Permission denied (publickey)', your SSH key is"
        echo "  not registered with GitHub. Use the plain HTTPS default instead:"
        echo "    bash script/push_wiki.sh   # no WIKI_SSH=1"
        echo ""
        exit 1
    fi
fi

echo "→ Copying docs/wiki/*.md → ${WIKI_TMP}/"
cp "${WIKI_SRC}"/*.md "${WIKI_TMP}/"

cd "${WIKI_TMP}"
git add -A
if git diff --cached --quiet; then
    echo "→ No changes to push."
else
    git commit -m "${MSG}"
    git push
    echo "→ Wiki updated: https://github.com/b202i/cross/wiki"
fi
