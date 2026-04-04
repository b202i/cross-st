#!/usr/bin/env bash
# script/smoke_test.sh — Post-publish smoke test for cross-st from PyPI.
#
# Installs the specified version into a fresh temporary pipx environment,
# runs a series of quick checks, then uninstalls it.
#
# Usage:
#   bash script/smoke_test.sh 0.2.0
#   bash script/smoke_test.sh          # uses latest from PyPI
#
# Requires:  pipx (brew install pipx / apt install pipx)
# Does NOT require API keys — all checks use --help or offline commands.

set -euo pipefail

VERSION="${1:-}"

# ── Helpers ────────────────────────────────────────────────────────────────────
_ok()   { echo "  ✅  $1"; }
_fail() { echo "  ❌  FAIL: $1" >&2; FAILURES=$((FAILURES + 1)); }
FAILURES=0

PKG="cross-st"
[[ -n "$VERSION" ]] && INSTALL_SPEC="${PKG}==${VERSION}" || INSTALL_SPEC="${PKG}"

echo
echo "  Cross smoke test"
echo "  ─────────────────────────────────────────────────────"
echo "  Installing : ${INSTALL_SPEC}"
echo "  ─────────────────────────────────────────────────────"

# ── Ensure pipx is available ──────────────────────────────────────────────────
if ! command -v pipx &>/dev/null; then
    echo "  ❌  pipx not found. Install with:  brew install pipx" >&2
    exit 1
fi

# ── Install into isolated venv ────────────────────────────────────────────────
SMOKE_HOME="$(mktemp -d)"
trap 'rm -rf "$SMOKE_HOME"' EXIT

echo
echo "  Installing ${INSTALL_SPEC} into isolated environment …"
PIPX_HOME="$SMOKE_HOME" pipx install "$INSTALL_SPEC" --quiet
PIPX_BIN="$SMOKE_HOME/bin"

run() {
    # run a command from the isolated pipx env
    local cmd="$PIPX_BIN/$1"
    shift
    "$cmd" "$@" 2>&1
}

echo

# ── 1. Version check ──────────────────────────────────────────────────────────
echo "  1. Version"
INSTALLED_VER="$(PIPX_HOME="$SMOKE_HOME" pipx runpip cross-st show cross-st 2>/dev/null \
    | awk '/^Version:/{print $2}')"
if [[ -n "$VERSION" && "$INSTALLED_VER" != "$VERSION" ]]; then
    _fail "Version mismatch: expected ${VERSION}, got ${INSTALLED_VER}"
else
    _ok "cross-st ${INSTALLED_VER} installed"
fi

# ── 2. Entry points present ───────────────────────────────────────────────────
echo
echo "  2. Entry points"
ENTRY_POINTS=(
    st st-admin st-analyze st-bang st-cat st-cross st-domain st-edit
    st-fact st-fetch st-find st-fix st-gen st-heatmap st-ls st-man
    st-merge st-new st-plot st-post st-prep st-print st-read st-rm
    st-speak st-speed st-stones st-verdict st-voice
)
MISSING=()
for ep in "${ENTRY_POINTS[@]}"; do
    [[ -f "$PIPX_BIN/$ep" ]] || MISSING+=("$ep")
done
if [[ ${#MISSING[@]} -gt 0 ]]; then
    _fail "Missing entry points: ${MISSING[*]}"
else
    _ok "All ${#ENTRY_POINTS[@]} entry points present"
fi

# ── 3. Core --help flags ──────────────────────────────────────────────────────
echo
echo "  3. --help flags (no API keys needed)"
for cmd in st-admin st-new st-ls st-find st-man st-stones; do
    if run "$cmd" --help &>/dev/null; then
        _ok "${cmd} --help"
    else
        _fail "${cmd} --help exited non-zero"
    fi
done

# ── 4. New B4 cache commands ──────────────────────────────────────────────────
echo
echo "  4. B4 cache commands"
# st-admin needs config to start, but --cache-info should work once require_config
# is satisfied. We test argument parsing via --help which always works.
if run st-admin --help 2>&1 | grep -q "cache-info"; then
    _ok "st-admin --cache-info in --help output"
else
    _fail "st-admin --cache-info not found in --help"
fi
if run st-admin --help 2>&1 | grep -q "cache-clear"; then
    _ok "st-admin --cache-clear in --help output"
else
    _fail "st-admin --cache-clear not found in --help"
fi
if run st-admin --help 2>&1 | grep -q "cache-cull"; then
    _ok "st-admin --cache-cull in --help output"
else
    _fail "st-admin --cache-cull not found in --help"
fi

# ── 5. Importability ─────────────────────────────────────────────────────────
echo
echo "  5. Package imports"
PYTHON="$SMOKE_HOME/venvs/cross-st/bin/python"
if "$PYTHON" -c "from cross_st import commands" 2>&1; then
    _ok "cross_st.commands importable"
else
    _fail "cross_st.commands import failed"
fi
if "$PYTHON" -c "from importlib.metadata import version; assert version('cross-st') == '${VERSION:-$INSTALLED_VER}'" 2>&1; then
    _ok "importlib.metadata version == ${VERSION:-$INSTALLED_VER}"
else
    _fail "importlib.metadata version mismatch"
fi

# ── 6. st-man renders without error ──────────────────────────────────────────
echo
echo "  6. st-man"
if run st-man 2>&1 | grep -qi "cross\|usage\|command"; then
    _ok "st-man produces output"
else
    _fail "st-man produced no recognisable output"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo
echo "  ─────────────────────────────────────────────────────"
if [[ $FAILURES -eq 0 ]]; then
    echo "  ✅  All checks passed — cross-st ${INSTALLED_VER} is good to go!"
else
    echo "  ❌  ${FAILURES} check(s) failed — review output above"
    exit 1
fi
echo

